import {spawn} from 'child_process'

export interface CommandOptions {
  cwd: string
  timeoutMs: number
  maxBuffer: number
  env?: NodeJS.ProcessEnv
  input?: string
}

export function command(executable: string, args: string[], options: CommandOptions): Promise<string> {
  if (options.timeoutMs <= 0) return Promise.reject(new Error(`${executable}: budget exhausted`))
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd: options.cwd, env: {...process.env, ...options.env}, detached: true,
      stdio: ['pipe', 'pipe', 'pipe']
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
      if (failure) reject(failure)
      else if (code !== 0) reject(new Error(`${executable}: exited ${code}: ${Buffer.concat(stderr).toString('utf8')}`))
      else resolve(Buffer.concat(stdout).toString('utf8'))
    })
    child.stdin.on('error', () => undefined)
    child.stdin.end(options.input)
  })
}
