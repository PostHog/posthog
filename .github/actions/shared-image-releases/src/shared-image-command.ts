import {ChildProcessWithoutNullStreams, spawn, SpawnOptionsWithoutStdio} from 'child_process'
import {accessSync, constants, realpathSync, statSync} from 'fs'
import * as path from 'path'

export type CommandExecutable = 'git' | 'aws' | 'helper' | 'client'
export interface CommandOptions {
  cwd: string
  timeoutMs: number
  maxBuffer: number
  env?: NodeJS.ProcessEnv
  input?: string
  onStderr?: (output: string) => void
}

const clients = new Map<string, string>()

export function configureCopyClient(executable: string): string {
  const cached = clients.get(executable)
  if (cached) return cached
  if (!path.isAbsolute(executable) || path.basename(executable) !== 'regctl' || !statSync(executable).isFile()) {
    throw new Error('Copy client must be an absolute path to the installed regctl file')
  }
  accessSync(executable, constants.X_OK)
  const resolved = realpathSync(executable)
  clients.set(executable, resolved)
  return resolved
}

function launch(executable: CommandExecutable, args: string[], options: SpawnOptionsWithoutStdio): ChildProcessWithoutNullStreams {
  switch (executable) {
    case 'git': return spawn('git', args, options)
    case 'aws': return spawn('aws', args, options)
    case 'helper': return spawn('bash', args, options)
    case 'client': return spawn('sh', ['-c', 'exec "$REGCTL" "$@"', 'regctl', ...args], options)
  }
}

export function command(executable: CommandExecutable, args: string[], options: CommandOptions): Promise<string> {
  if (options.timeoutMs <= 0) return Promise.reject(new Error(`${executable}: budget exhausted`))
  return new Promise((resolve, reject) => {
    const child = launch(executable, args, {
      cwd: options.cwd, env: {...process.env, ...options.env}, detached: true
    })
    const stdout: Buffer[] = []
    const stderr: Buffer[] = []
    let bytes = 0
    let failure: Error | undefined
    const stop = (message: string): void => {
      failure = new Error(`${executable}: ${message}`)
      if (child.pid) {
        try { process.kill(-child.pid, 'SIGKILL') } catch { child.kill('SIGKILL') }
      }
    }
    const timer = setTimeout(() => stop('timed out'), options.timeoutMs)
    const collect = (chunks: Buffer[]) => (chunk: Buffer): void => {
      bytes += chunk.length
      if (bytes > options.maxBuffer) stop('output budget exhausted')
      else chunks.push(chunk)
    }
    child.stdout.on('data', collect(stdout))
    child.stderr.on('data', collect(stderr))
    child.on('error', error => { clearTimeout(timer); reject(error) })
    child.on('close', code => {
      clearTimeout(timer)
      if (failure) {
        const diagnostics = Buffer.concat(stderr).subarray(-4096).toString('utf8').trim()
        if (diagnostics) {
          failure.message += `: ${diagnostics}`
          options.onStderr?.(diagnostics)
        }
        reject(failure)
      }
      else if (code !== 0) reject(new Error(`${executable}: exited ${code}: ${Buffer.concat(stderr).toString('utf8')}`))
      else {
        options.onStderr?.(Buffer.concat(stderr).toString('utf8'))
        resolve(Buffer.concat(stdout).toString('utf8'))
      }
    })
    child.stdin.on('error', () => undefined)
    child.stdin.end(options.input)
  })
}
