import {execFileSync} from 'child_process'
import {mkdtempSync, readFileSync, rmSync, writeFileSync, chmodSync, existsSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {command, configureCopyClient} from '../src/shared-image-command'

let cwd: string
beforeEach(() => { cwd = mkdtempSync(path.join(tmpdir(), 'shared-image-command-')) })
afterEach(() => rmSync(cwd, {recursive: true, force: true}))

function hasGnuTimeout(): boolean {
  try {
    if (execFileSync('timeout', ['--version'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).includes('GNU coreutils')) return true
  } catch {}
  process.stdout.write('SKIP supervised helper timeout: GNU coreutils timeout is unavailable\n')
  return false
}

describe('bounded shared-image processes', () => {
  test('timeout kills the process group, including a sleeping grandchild', async () => {
    const pidFile = path.join(cwd, 'grandchild.pid')
    await expect(command('helper', ['-c', 'sleep 30 & echo "$!" > "$1"; wait', 'fixture', pidFile], {
      cwd, timeoutMs: 200, maxBuffer: 1024
    })).rejects.toThrow('timed out')
    const pid = Number(readFileSync(pidFile, 'utf8').trim())
    const deadline = Date.now() + 2000
    let exists = true
    while (exists && Date.now() < deadline) {
      try { process.kill(pid, 0) } catch { exists = false }
      if (exists) await new Promise<void>(resolve => setImmediate(resolve))
    }
    try { expect(exists).toBe(false) } finally {
      if (exists) process.kill(pid, 'SIGKILL')
    }
  })

  const timeoutTest = hasGnuTimeout() ? test : test.skip
  timeoutTest('timeout kills the real helper copy without later completion', async () => {
    const client = path.join(cwd, 'regctl')
    const aws = path.join(cwd, 'aws')
    const marker = path.join(cwd, 'completed')
    const started = path.join(cwd, 'started')
    writeFileSync(client, '#!/bin/sh\nprintf started > "$STARTED"\nsleep 1\nprintf completed > "$MARKER"\n')
    writeFileSync(aws, '#!/bin/sh\nprintf "None\\n"\n')
    chmodSync(client, 0o755); chmodSync(aws, 0o755)
    const timeoutMs = 200
    const begin = Date.now()
    await expect(command('helper', [path.resolve(__dirname, '../../../scripts/ordered-image-release.sh'), 'publish'], {
      cwd, timeoutMs, maxBuffer: 4096,
      env: {PATH: `${cwd}:${process.env.PATH}`, REGCTL: client, STARTED: started, MARKER: marker,
        ECR_REGISTRY: 'registry.example.com', ECR_REPO: 'fixture', ORDERED_ALIAS: 'r000000000002-abcdef',
        EXPECTED_DIGEST: `sha256:${'a'.repeat(64)}`, COPY_TIMEOUT_SECONDS: '10', READBACK_TIMEOUT_SECONDS: '10'}
    })).rejects.toThrow('timed out')
    const reportedMs = Date.now() - begin
    expect(existsSync(started)).toBe(true)
    await new Promise<void>(resolve => setTimeout(resolve, 1500))
    const completed = existsSync(marker)
    process.stdout.write(JSON.stringify({deadlineMs: timeoutMs, reportedMs, observationMs: Date.now() - begin, completed}) + '\n')
    expect(completed).toBe(false)
  }, 10000)

  test.each(['stdout', 'stderr'])('output on %s beyond maxBuffer rejects even if the child exits successfully', async stream => {
    const diagnostic = jest.fn()
    await expect(command('helper', ['-c', `printf 1234567890 ${stream === 'stderr' ? '>&2' : ''}`], {cwd, timeoutMs: 10000, maxBuffer: 4, onStderr: diagnostic})).rejects.toThrow('output budget exhausted')
    expect(diagnostic).not.toHaveBeenCalled()
  })

  test.each(['timed out', 'output budget exhausted'])('killed helper retains bounded stderr after %s', async failure => {
    const diagnostic = jest.fn()
    const stderr = `${failure === 'output budget exhausted' ? `discarded prefix\n${'x'.repeat(5000)}\n` : ''}fixture primary diagnostic\n`
    const script = `printf '%s' "$1" >&2; ${failure === 'timed out' ? 'sleep 30' : "printf '%*s' 2097152 ''"}`
    await expect(command('helper', ['-c', script, 'fixture', stderr], {
      cwd, timeoutMs: failure === 'timed out' ? 200 : 10000, maxBuffer: 1024 * 1024, onStderr: diagnostic
    })).rejects.toThrow(`helper: ${failure}: ${stderr.slice(-4096).trim()}`)
    expect(diagnostic).toHaveBeenCalledTimes(1)
    expect(diagnostic).toHaveBeenCalledWith(stderr.slice(-4096).trim())
  })

  test('successful command stderr is retained independently of stdout', async () => {
    const diagnostic = jest.fn()
    expect(await command('helper', ['-c', 'printf result; printf diagnostic >&2'], {cwd, timeoutMs: 10000, maxBuffer: 1024, onStderr: diagnostic})).toBe('result')
    expect(diagnostic).toHaveBeenCalledWith('diagnostic')
  })

  test('the configured client preserves literal arguments through the fixed executable dispatch', async () => {
    const file = path.join(cwd, 'regctl')
    writeFileSync(file, '#!/bin/sh\nprintf "%s\\n" "$1"\n')
    chmodSync(file, 0o755)
    const client = configureCopyClient(file)
    expect(await command('client', ['literal $(not-executed)'], {cwd, timeoutMs: 10000, maxBuffer: 1024, env: {REGCTL: client}})).toBe('literal $(not-executed)\n')
    expect(() => configureCopyClient('regctl')).toThrow('absolute path')
  })
})
