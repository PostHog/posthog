import {mkdtempSync, readFileSync, rmSync, writeFileSync, chmodSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {command, configureCopyClient} from '../src/shared-image-command'

let cwd: string
beforeEach(() => { cwd = mkdtempSync(path.join(tmpdir(), 'shared-image-command-')) })
afterEach(() => rmSync(cwd, {recursive: true, force: true}))

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

  test('output beyond maxBuffer rejects even if the child exits successfully', async () => {
    await expect(command('helper', ['-c', 'printf 1234567890'], {cwd, timeoutMs: 10000, maxBuffer: 4})).rejects.toThrow('output budget exhausted')
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
