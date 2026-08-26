import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus} from '../src/file'
import {compareWithMergeCommit} from '../src/shadow'

const exec = jest.requireMock('@actions/exec') as {getExecOutput: jest.Mock}

jest.mock('@actions/exec', () => ({getExecOutput: jest.fn()}))
jest.mock('@actions/core', () => ({info: jest.fn(), warning: jest.fn(), startGroup: jest.fn(), endGroup: jest.fn()}))

const HEAD = 'a'.repeat(40)
const GIT_DIR = '/tmp/runner/paths-filter-shadow.git'

describe('shadow merge-commit comparison', () => {
  // A --depth or --filter fetch rewrites the shallow boundary and promisor config of
  // whichever repository it runs in. Steps after this action read history from the
  // workspace checkout: ci-dagster and ci-e2e-playwright resolve
  // `git merge-base HEAD^2 origin/<base>` there, and an empty merge base silently
  // drops their schema cache. So every call has to name the scratch git dir.
  test('never runs git against the job workspace', async () => {
    process.env.RUNNER_TEMP = '/tmp/runner'
    process.env.GITHUB_SERVER_URL = 'https://github.com'
    process.env.GITHUB_REPOSITORY = 'PostHog/posthog'
    exec.getExecOutput.mockReset()
    for (const stdout of ['', '', HEAD, 'a.ts\0']) {
      exec.getExecOutput.mockResolvedValueOnce({exitCode: 0, stdout, stderr: ''})
    }

    const result = await compareWithMergeCommit([{filename: 'a.ts', status: ChangeStatus.Modified}], {
      number: 42,
      head: {sha: HEAD}
    } as PullRequest)

    expect(result.verdict).toBe('match')
    const calls = exec.getExecOutput.mock.calls.map(c => c[1] as string[])
    expect(calls[0]).toEqual(['init', '--bare', '--quiet', GIT_DIR])
    for (const argv of calls.slice(1)) {
      expect(argv.slice(0, 2)).toEqual(['--git-dir', GIT_DIR])
    }
  })
})
