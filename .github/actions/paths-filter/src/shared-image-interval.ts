import {execFileSync} from 'child_process'
import {Filter} from './filter'
import {File} from './file'
import {parseGitDiffOutput} from './git'

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
  const history = git(['rev-list', '--first-parent', revision]).trim().split('\n')
  if (!history.includes(base)) throw new Error('Frontier is outside the executing first-parent history')
  const output = git(['log', '--first-parent', '--diff-merges=first-parent', '--format=', '--no-renames', '--name-status', '-z', `${base}..${revision}`])
  const files = parseGitDiffOutput(output)
  if (files.some(file => file.status === undefined)) throw new Error('Unsupported Git change status')
  return files
}

export function matchInterval(filter: Filter, files: File[]): ReturnType<Filter['match']> {
  return filter.match(files)
}
