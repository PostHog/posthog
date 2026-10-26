import {execFileSync} from 'child_process'
import {File} from '../../paths-filter/src/file'
import {parseGitDiffOutput} from '../../paths-filter/src/git'

export interface IntervalOptions {
  cwd: string
  timeoutMs: number
  maxBuffer: number
}

export function intervalFiles(base: string, revision: string, options: IntervalOptions): File[] {
  if (!/^[0-9a-f]{40}$/.test(base) || !/^[0-9a-f]{40}$/.test(revision)) {
    throw new Error('Interval requires full source revisions')
  }
  const deadline = Date.now() + options.timeoutMs
  const git = (args: string[]): string => {
    const timeout = deadline - Date.now()
    if (timeout <= 0) throw new Error('Source history comparison timed out')
    return execFileSync('git', args, {
      cwd: options.cwd, maxBuffer: options.maxBuffer, timeout, encoding: 'utf8',
      env: {...process.env, GIT_NO_LAZY_FETCH: '1'}, stdio: ['ignore', 'pipe', 'pipe']
    })
  }
  if (git(['rev-parse', '--is-shallow-repository']).trim() !== 'false') {
    throw new Error('Complete executing source history is unavailable')
  }
  if (git(['rev-parse', 'HEAD']).trim() !== revision) throw new Error('Built revision differs from executing checkout')
  if (base === revision) return []
  const history = git(['rev-list', '--first-parent', revision, '--not', base]).trim().split('\n').filter(Boolean)
  const last = history[history.length - 1]
  if (!last || git(['rev-list', '--parents', '--max-count=1', last]).trim().split(/\s+/)[1] !== base) {
    throw new Error('Frontier is outside the executing first-parent history')
  }
  const output = git(['log', '--first-parent', '--diff-merges=first-parent', '--format=', '--no-renames', '--name-status', '-z', `${base}..${revision}`])
  const normalized = output.split('\0').filter(Boolean).map((token, index) => index % 2 === 0 && token === 'T' ? 'M' : token).join('\0')
  const files = parseGitDiffOutput(normalized)
  if (files.some(file => file.status === undefined)) throw new Error('Unsupported Git change status')
  return files
}
