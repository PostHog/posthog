import {execFile} from 'child_process'
import * as os from 'os'
import * as path from 'path'

import * as core from '@actions/core'
import {PullRequest} from '@octokit/webhooks-types'

import {File} from './file'

// Compares the API's changed-file list against the same list derived locally from
// the pull request's merge commit, and reports disagreement without acting on it.
// The API result stays authoritative, so a wrong local answer can only produce a
// log line. Removing the API call later is only safe once this has run quiet
// across the shapes no offline sample can reach: very large diffs, and ones GitHub
// has not finished computing a merge ref for.
//
// Detecting changes from `base.sha..HEAD` instead reports every commit the branch
// picked up when the base was merged into it as the pull request's own work, which
// is wrong by thousands of files on a branch that has taken master in. The merge
// commit's first parent is the base GitHub actually merged against, so
// `HEAD^1..HEAD` is the pull request's own changes and matches the API.

const MERGE_REF_FETCH_DEPTH = 2
const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'paths_filter_shadow_compared'

// A change-detection job is on the critical path of every workflow, so the comparison
// and the capture that follows it share one wall-clock budget, and give up rather than
// holding the job to its timeout-minutes. The git-level low-speed settings cover a
// stalled transfer; the budget covers everything else.
const BUDGET_MS = 20000
const CAPTURE_FLOOR_MS = 500
const LIST_CAP = 50

// A queue branch carries the cumulative batch diff, so the path list can be far larger
// than a human pull request's. execFile's 1 MB default would fail those as a diff error,
// which drops the population the comparison most needs to measure.
const MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
const DETAIL_CAP = 200

// The API caps pulls/{n}/files at this many entries and says nothing when it truncates.
const API_FILE_CAP = 3000

type Verdict = 'match' | 'mismatch' | 'unavailable'

// A closed set, because this is the field the comparison is grouped by once the events
// land. Git's own words go in `detail`, which is free text and unbounded.
type Reason =
  | 'no-scratch-repo'
  | 'no-origin-url'
  | 'no-merge-ref'
  | 'no-second-parent'
  | 'stale-merge-ref'
  | 'diff-failed'
  | 'budget-exceeded'
  | 'unknown'

class Unavailable extends Error {
  constructor(readonly reason: Reason, readonly detail: string) {
    super(`${reason}: ${detail}`)
  }
}

interface Difference {
  count: number
  sample: string[]
}

interface ShadowResult {
  verdict: Verdict
  reason: Reason | null
  detail: string | null
  apiCount: number
  gitCount: number | null
  onlyInApi: Difference
  onlyInGit: Difference
}

interface GitResult {
  code: number
  out: string
  err: string
}

// Every git call that reads or writes history names the scratch repository. `--depth`
// and `--filter` rewrite `.git/shallow` and the promisor config of whatever repository
// they run in, and steps later in the same job read history from the workspace checkout:
// ci-dagster and ci-e2e-playwright resolve `git merge-base HEAD^2 origin/<base>` after
// this action returns, and an empty merge base there silently drops their schema cache.
async function git(gitDir: string, args: string[], signal: AbortSignal): Promise<GitResult> {
  return run(['--git-dir', gitDir, ...args], signal)
}

// The signal is what makes the wall-clock budget real. `@actions/exec` gives no handle
// on the child process, so a fetch the budget gave up on keeps running and holds the
// action's process open until it finishes, past the budget it was supposed to obey.
//
// stdout is returned raw. A caller that reads a path list must not trim it, because a
// tracked path can begin with a space, and that path sorts first in the -z output.
async function run(args: string[], signal: AbortSignal): Promise<GitResult> {
  return new Promise(resolve => {
    execFile('git', args, {signal, maxBuffer: MAX_GIT_OUTPUT_BYTES}, (error, stdout, stderr) => {
      resolve({code: error ? 1 : 0, out: stdout, err: stderr.trim()})
    })
  })
}

function firstLine(stderr: string): string {
  return stderr.slice(0, DETAIL_CAP).split('\n')[0] || 'no stderr'
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function scratchRepo(signal: AbortSignal): Promise<string> {
  const gitDir = path.join(process.env.RUNNER_TEMP || os.tmpdir(), 'paths-filter-shadow.git')
  const init = await run(['init', '--bare', '--quiet', gitDir], signal)
  if (init.code !== 0) {
    throw new Unavailable('no-scratch-repo', firstLine(init.err))
  }
  return gitDir
}

// The workspace remote carries no credentials of its own: actions/checkout keeps the
// token in an http.extraheader the scratch repository does not inherit. A private
// remote therefore reports unavailable rather than comparing against a partial fetch.
function originUrl(): string {
  const server = process.env.GITHUB_SERVER_URL
  const repo = process.env.GITHUB_REPOSITORY
  if (!server || !repo) {
    throw new Unavailable('no-origin-url', 'GITHUB_SERVER_URL or GITHUB_REPOSITORY is unset')
  }
  return `${server}/${repo}`
}

// The merge ref is not guaranteed to be present or current: GitHub recomputes it
// asynchronously after a push. Requiring the second parent to equal the head SHA
// rejects a stale ref rather than reading it as this pull request's changes.
async function localChangedFiles(pr: PullRequest, signal: AbortSignal): Promise<string[]> {
  const gitDir = await scratchRepo(signal)

  const fetched = await git(
    gitDir,
    [
      '-c',
      'http.lowSpeedLimit=1000',
      '-c',
      'http.lowSpeedTime=10',
      'fetch',
      '--no-tags',
      '--filter=blob:none',
      `--depth=${MERGE_REF_FETCH_DEPTH}`,
      originUrl(),
      `refs/pull/${pr.number}/merge`
    ],
    signal
  )
  if (fetched.code !== 0) {
    throw new Unavailable('no-merge-ref', firstLine(fetched.err))
  }

  const head = await git(gitDir, ['rev-parse', 'FETCH_HEAD^2'], signal)
  if (head.code !== 0) {
    throw new Unavailable('no-second-parent', firstLine(head.err))
  }
  const headSha = head.out.trim()
  if (headSha !== pr.head.sha) {
    throw new Unavailable('stale-merge-ref', `^2=${headSha.slice(0, 8)}, head=${pr.head.sha.slice(0, 8)}`)
  }

  // --no-renames so a rename arrives as a delete plus an add, which is the shape
  // the API path builds by hand from `previous_filename`. -z because git quotes a
  // path holding a newline or a non-ASCII byte in the default format.
  const diff = await git(gitDir, ['diff', '--no-renames', '--name-only', '-z', 'FETCH_HEAD^1', 'FETCH_HEAD'], signal)
  if (diff.code !== 0) {
    throw new Unavailable('diff-failed', firstLine(diff.err))
  }
  return diff.out.split('\0').filter(Boolean)
}

// A queue branch can differ by thousands of paths, which is neither readable in a log
// line nor worth carrying as an event property. The count answers how far apart the two
// answers are, and the sample answers what kind of path is involved.
function difference(from: Set<string>, against: Set<string>): Difference {
  const sample: string[] = []
  let count = 0
  for (const filename of from) {
    if (against.has(filename)) {
      continue
    }
    count++
    if (sample.length < LIST_CAP) {
      sample.push(filename)
    }
  }
  return {count, sample}
}

function compare(api: Set<string>, local: Set<string>): ShadowResult {
  const onlyInApi = difference(api, local)
  const onlyInGit = difference(local, api)
  return {
    verdict: onlyInApi.count === 0 && onlyInGit.count === 0 ? 'match' : 'mismatch',
    reason: null,
    detail: null,
    apiCount: api.size,
    gitCount: local.size,
    onlyInApi,
    onlyInGit
  }
}

async function budgeted<T>(work: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController()
  let timer: NodeJS.Timeout
  const expiry = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort()
      reject(new Unavailable('budget-exceeded', `${ms}ms`))
    }, ms)
  })
  return Promise.race([work(controller.signal), expiry]).finally(() => clearTimeout(timer))
}

export async function compareWithMergeCommit(apiFiles: File[], pr: PullRequest): Promise<ShadowResult> {
  const api = new Set(apiFiles.map(f => f.filename))
  try {
    const gitFiles = await budgeted(async signal => localChangedFiles(pr, signal), BUDGET_MS)
    return compare(api, new Set(gitFiles))
  } catch (error) {
    return {
      verdict: 'unavailable',
      reason: error instanceof Unavailable ? error.reason : 'unknown',
      detail: error instanceof Unavailable ? error.detail : messageOf(error),
      apiCount: api.size,
      gitCount: null,
      onlyInApi: {count: 0, sample: []},
      onlyInGit: {count: 0, sample: []}
    }
  }
}

// Without this the only record of a divergence is a log line in one job of one run,
// which is unreadable at the volume that makes the comparison worth running.
async function capture(apiKey: string, result: ShadowResult, pr: PullRequest, durationMs: number): Promise<void> {
  const repo = process.env.GITHUB_REPOSITORY || null
  const properties = {
    repo,
    verdict: result.verdict,
    reason: result.reason,
    detail: result.detail,
    api_count: result.apiCount,
    git_count: result.gitCount,
    only_in_api: result.onlyInApi.sample,
    only_in_api_count: result.onlyInApi.count,
    only_in_git: result.onlyInGit.sample,
    only_in_git_count: result.onlyInGit.count,
    // pulls/{n}/files truncates silently, so record both sides of the tell: what the
    // API returned, and what the pull request payload says it should have been. The
    // count has to come from the payload, because `api_count` counts a rename twice:
    // the API path expands each renamed row into an add plus a delete.
    api_truncated: pr.changed_files >= API_FILE_CAP,
    pr_changed_files: pr.changed_files,
    pr_number: pr.number,
    head_sha: pr.head.sha,
    head_ref: pr.head.ref,
    base_ref: pr.base.ref,
    // Queue branches carry the cumulative batch diff and page far more than a human
    // pull request, so they are the population worth reading separately.
    branch_class: pr.head.ref.startsWith('trunk-merge/') ? 'trunk-merge' : 'pull-request',
    is_fork: pr.head.repo?.full_name !== repo,
    duration_ms: durationMs,
    workflow: process.env.GITHUB_WORKFLOW || null,
    job: process.env.GITHUB_JOB || null,
    run_id: process.env.GITHUB_RUN_ID || null,
    run_attempt: process.env.GITHUB_RUN_ATTEMPT || null
  }
  const res = await fetch(`${POSTHOG_HOST}/capture/`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      api_key: apiKey,
      event: EVENT_NAME,
      distinct_id: repo || 'paths-filter-shadow',
      properties
    }),
    // Whatever the comparison did not spend, so the step's ceiling stays the budget.
    signal: AbortSignal.timeout(Math.max(CAPTURE_FLOOR_MS, BUDGET_MS - durationMs))
  })
  if (!res.ok) {
    throw new Error(`capture ${res.status}`)
  }
}

function summarize(result: ShadowResult): string {
  if (result.verdict === 'unavailable') {
    return `unavailable (${result.reason}: ${result.detail})`
  }
  if (result.verdict === 'mismatch') {
    return (
      `MISMATCH api=${result.apiCount} git=${result.gitCount} ` +
      `onlyInApi=${JSON.stringify(result.onlyInApi.sample)} onlyInGit=${JSON.stringify(result.onlyInGit.sample)}`
    )
  }
  return `match (${result.apiCount} files)`
}

// Never throws: the filter's real answer is already computed by the time this runs,
// so nothing here is worth failing a CI job over.
//
// The token gates the comparison itself, not just the capture. Every workflow that
// detects changes runs this action, so a comparison whose result cannot be recorded
// is a merge-ref fetch on the critical path of a gate job in exchange for a log line
// nobody reads. Fork pull requests get no secrets, so they take this path too.
export async function report(apiFiles: File[], pr: PullRequest): Promise<void> {
  const apiKey = process.env.PATHS_FILTER_SHADOW_POSTHOG_TOKEN
  if (!apiKey) {
    return
  }
  try {
    core.startGroup('Shadow: merge-commit change detection')
    const startedAt = Date.now()
    const result = await compareWithMergeCommit(apiFiles, pr)
    const durationMs = Date.now() - startedAt

    // core.info even for a mismatch: a warning becomes an annotation on the run summary
    // and the checks page, which reads as a problem with the pull request.
    core.info(`shadow: ${summarize(result)} in ${durationMs}ms`)

    await capture(apiKey, result, pr, durationMs).catch(error => {
      core.info(`shadow: capture skipped (${messageOf(error)})`)
    })
  } catch (error) {
    core.info(`shadow: skipped (${messageOf(error)})`)
  } finally {
    core.endGroup()
  }
}
