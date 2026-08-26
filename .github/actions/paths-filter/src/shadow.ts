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
async function originUrl(): Promise<string> {
  const server = process.env.GITHUB_SERVER_URL
  const repo = process.env.GITHUB_REPOSITORY
  if (server && repo) {
    return `${server}/${repo}`
  }
  const remote = await getExecOutput('git', ['remote', 'get-url', 'origin'], {
    ignoreReturnCode: true,
    silent: true
  })
  if (remote.exitCode !== 0 || !remote.stdout.trim()) {
    throw new Error('cannot resolve origin url')
  }
  return remote.stdout.trim()
}

// The merge ref is not guaranteed to be present or current: GitHub recomputes it
// asynchronously after a push. Requiring the second parent to equal the head SHA
// rejects a stale ref rather than reading it as this pull request's changes.
async function localChangedFiles(pr: PullRequest): Promise<string[]> {
  const gitDir = await scratchRepo()
  const url = await originUrl()

  const fetched = await git(gitDir, [
    'fetch',
    '--no-tags',
    '--filter=blob:none',
    `--depth=${MERGE_REF_FETCH_DEPTH}`,
    url,
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
  // the API path builds by hand from `previous_filename`.
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
    onlyInApi: onlyInApi.slice(0, 20),
    onlyInGit: onlyInGit.slice(0, 20)
  }
}

export async function compareWithMergeCommit(apiFiles: File[], pr: PullRequest): Promise<ShadowResult> {
  try {
    return compare(apiFiles, await localChangedFiles(pr))
  } catch (error) {
    return {
      verdict: 'unavailable',
      reason: error instanceof Error ? error.message : String(error),
      apiCount: apiFiles.length
    }
  }
}

// Never throws: the filter's real answer is already computed by the time this runs,
// so nothing here is worth failing a CI job over.
export async function report(apiFiles: File[], pr: PullRequest): Promise<void> {
  try {
    core.startGroup('Shadow: merge-commit change detection')
    const result = await compareWithMergeCommit(apiFiles, pr)
    if (result.verdict === 'match') {
      core.info(`shadow: match (${result.apiCount} files)`)
    } else if (result.verdict === 'unavailable') {
      core.info(`shadow: unavailable (${result.reason})`)
    } else {
      core.warning(
        `shadow: MISMATCH api=${result.apiCount} git=${result.gitCount} ` +
          `onlyInApi=${JSON.stringify(result.onlyInApi)} onlyInGit=${JSON.stringify(result.onlyInGit)}`
      )
    }
  } catch (error) {
    core.info(`shadow: skipped (${error instanceof Error ? error.message : String(error)})`)
  } finally {
    core.endGroup()
  }
}
