import * as os from 'os'
import * as path from 'path'

import * as core from '@actions/core'
import {getExecOutput} from '@actions/exec'
import {PullRequest} from '@octokit/webhooks-types'

import {File} from './file'

// Compares the API's changed-file list against the same list derived locally from
// the pull request's merge commit, and reports disagreement without acting on it.
// The API result stays authoritative, so a wrong local answer can only produce a
// log line. Removing the API call later is only safe once this has run quiet
// across the shapes no offline sample can reach: merged pull requests, very large
// diffs, and ones GitHub has not finished computing a merge ref for.
//
// Detecting changes from `base.sha..HEAD` instead reports every commit the branch
// picked up when the base was merged into it as the pull request's own work, which
// is wrong by thousands of files on a branch that has taken master in. The merge
// commit's first parent is the base GitHub actually merged against, so
// `HEAD^1..HEAD` is the pull request's own changes and matches the API.

const MERGE_REF_FETCH_DEPTH = 2
const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'paths_filter_shadow_compared'

// A change-detection job is on the critical path of every workflow, so the whole
// comparison gets a wall-clock budget and gives up rather than holding the job to
// its timeout-minutes. The git-level low-speed settings cover a stalled transfer;
// the budget covers everything else.
const BUDGET_MS = 20000
const CAPTURE_TIMEOUT_MS = 5000
const LIST_CAP = 50

// The API caps pulls/{n}/files at this many entries and says nothing when it truncates.
const API_FILE_CAP = 3000

type Verdict = 'match' | 'mismatch' | 'unavailable'

interface ShadowResult {
  verdict: Verdict
  reason?: string
  apiCount: number
  gitCount?: number
  onlyInApi?: string[]
  onlyInGit?: string[]
}

// Every git call is confined to a scratch repository. `--depth` and `--filter`
// rewrite `.git/shallow` and the promisor config of whatever repository they run
// in, and steps later in the same job read history from the workspace checkout:
// ci-dagster and ci-e2e-playwright resolve `git merge-base HEAD^2 origin/<base>`
// after this action returns, and an empty merge base there silently drops their
// schema cache.
async function git(gitDir: string, args: string[]): Promise<{code: number; out: string}> {
  const res = await getExecOutput('git', ['--git-dir', gitDir, ...args], {
    ignoreReturnCode: true,
    silent: true
  })
  return {code: res.exitCode, out: res.stdout.trim()}
}

async function scratchRepo(): Promise<string> {
  const gitDir = path.join(process.env.RUNNER_TEMP || os.tmpdir(), 'paths-filter-shadow.git')
  const init = await getExecOutput('git', ['init', '--bare', '--quiet', gitDir], {
    ignoreReturnCode: true,
    silent: true
  })
  if (init.exitCode !== 0) {
    throw new Error('cannot create scratch repository')
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
    throw new Error('cannot resolve origin url')
  }
  return `${server}/${repo}`
}

// The merge ref is not guaranteed to be present or current: GitHub recomputes it
// asynchronously after a push. Requiring the second parent to equal the head SHA
// rejects a stale ref rather than reading it as this pull request's changes.
async function localChangedFiles(pr: PullRequest): Promise<string[]> {
  const gitDir = await scratchRepo()

  const fetched = await git(gitDir, [
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
  ])
  if (fetched.code !== 0) {
    throw new Error('no merge ref')
  }

  const head = await git(gitDir, ['rev-parse', 'FETCH_HEAD^2'])
  if (head.code !== 0) {
    throw new Error('merge ref has no second parent')
  }
  if (head.out !== pr.head.sha) {
    throw new Error(`merge ref is stale (^2=${head.out.slice(0, 8)}, head=${pr.head.sha.slice(0, 8)})`)
  }

  // --no-renames so a rename arrives as a delete plus an add, which is the shape
  // the API path builds by hand from `previous_filename`. -z because git quotes a
  // path holding a newline or a non-ASCII byte in the default format.
  const diff = await git(gitDir, ['diff', '--no-renames', '--name-only', '-z', 'FETCH_HEAD^1', 'FETCH_HEAD'])
  if (diff.code !== 0) {
    throw new Error('diff failed')
  }
  return diff.out.split('\0').filter(Boolean)
}

function compare(apiFiles: File[], gitFiles: string[]): ShadowResult {
  const api = new Set(apiFiles.map(f => f.filename))
  const local = new Set(gitFiles)
  const onlyInApi = [...api].filter(f => !local.has(f))
  const onlyInGit = [...local].filter(f => !api.has(f))
  return {
    verdict: onlyInApi.length === 0 && onlyInGit.length === 0 ? 'match' : 'mismatch',
    apiCount: api.size,
    gitCount: local.size,
    onlyInApi: onlyInApi.slice(0, LIST_CAP),
    onlyInGit: onlyInGit.slice(0, LIST_CAP)
  }
}

function budgeted<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout
  const expiry = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`exceeded ${ms}ms budget`)), ms)
  })
  return Promise.race([work, expiry]).finally(() => clearTimeout(timer)) as Promise<T>
}

export async function compareWithMergeCommit(apiFiles: File[], pr: PullRequest): Promise<ShadowResult> {
  try {
    return compare(apiFiles, await budgeted(localChangedFiles(pr), BUDGET_MS))
  } catch (error) {
    return {
      verdict: 'unavailable',
      reason: error instanceof Error ? error.message : String(error),
      apiCount: apiFiles.length
    }
  }
}

// Without this the only record of a divergence is a log line in one job of one run,
// which is unreadable at the volume that makes the comparison worth running.
// Forks get no secrets, so the token is absent there and the capture is skipped.
async function capture(result: ShadowResult, pr: PullRequest, durationMs: number): Promise<void> {
  const apiKey = process.env.PATHS_FILTER_SHADOW_POSTHOG_TOKEN
  if (!apiKey) {
    return
  }
  const repo = process.env.GITHUB_REPOSITORY || null
  const headRef = pr.head?.ref ?? null
  const properties = {
    repo,
    verdict: result.verdict,
    reason: result.reason ?? null,
    api_count: result.apiCount,
    git_count: result.gitCount ?? null,
    only_in_api: result.onlyInApi ?? [],
    only_in_git: result.onlyInGit ?? [],
    // pulls/{n}/files truncates silently, so record both sides of the tell: what the
    // API returned, and what the pull request payload says it should have been.
    api_truncated: result.apiCount >= API_FILE_CAP,
    pr_changed_files: typeof pr.changed_files === 'number' ? pr.changed_files : null,
    pr_number: pr.number,
    head_sha: pr.head?.sha ?? null,
    head_ref: headRef,
    base_ref: pr.base?.ref ?? null,
    // Queue branches carry the cumulative batch diff and page far more than a human
    // pull request, so they are the population worth reading separately.
    branch_class: headRef?.startsWith('trunk-merge/') ? 'trunk-merge' : 'pull-request',
    is_fork: pr.head?.repo?.full_name !== repo,
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
    signal: AbortSignal.timeout(CAPTURE_TIMEOUT_MS)
  })
  if (!res.ok) {
    throw new Error(`capture ${res.status}`)
  }
}

// Never throws: the filter's real answer is already computed by the time this runs,
// so nothing here is worth failing a CI job over.
export async function report(apiFiles: File[], pr: PullRequest): Promise<void> {
  try {
    core.startGroup('Shadow: merge-commit change detection')
    const startedAt = Date.now()
    const result = await compareWithMergeCommit(apiFiles, pr)
    const durationMs = Date.now() - startedAt

    if (result.verdict === 'mismatch') {
      core.warning(
        `shadow: MISMATCH api=${result.apiCount} git=${result.gitCount} ` +
          `onlyInApi=${JSON.stringify(result.onlyInApi)} onlyInGit=${JSON.stringify(result.onlyInGit)}`
      )
    } else if (result.verdict === 'unavailable') {
      core.info(`shadow: unavailable (${result.reason}) in ${durationMs}ms`)
    } else {
      core.info(`shadow: match (${result.apiCount} files) in ${durationMs}ms`)
    }

    await capture(result, pr, durationMs).catch(error => {
      core.info(`shadow: capture skipped (${error instanceof Error ? error.message : String(error)})`)
    })
  } catch (error) {
    core.info(`shadow: skipped (${error instanceof Error ? error.message : String(error)})`)
  } finally {
    core.endGroup()
  }
}
