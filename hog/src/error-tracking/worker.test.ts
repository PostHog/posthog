import { describe, expect, test } from 'bun:test'
import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Worker, WORKER_PROTOCOL, workerPath } from './worker'

const EXECUTABLE = 0o755

function program(script: string): string {
    const path = join(mkdtempSync(join(tmpdir(), 'hog-worker-test-')), 'hog-worker')
    writeFileSync(path, `#!/bin/sh\n${script}\n`)
    chmodSync(path, EXECUTABLE)
    return path
}

const detect = (path: string): Promise<unknown> =>
    new Worker(path).detect([{ path: '/build/a.js', bundle: true, map: false }], undefined)

describe('starting hog-worker', () => {
    test.each([
        [
            'a worker from another release',
            `echo '{"type":"hello","protocol":${WORKER_PROTOCOL + 1},"version":"9.9.9"}'; cat > /dev/null`,
            `speaks protocol ${WORKER_PROTOCOL + 1}`,
        ],
        ['a program that is not hog-worker', 'echo hello; cat > /dev/null', "didn't answer like hog-worker"],
    ])('refuses %s', async (_name, script, message) => {
        const failure = await detect(program(script)).catch((error: unknown) => error)

        expect(failure).toMatchObject({ code: 'worker_mismatch', message: expect.stringContaining(message) })
    })

    test('names the path when the worker is not there', async () => {
        const path = join(tmpdir(), 'hog-worker-test-missing', 'hog-worker')

        const failure = await detect(path).catch((error: unknown) => error)

        expect(failure).toMatchObject({ code: 'worker_missing', message: expect.stringContaining(path) })
    })

    test('sends a person who runs it to hog', async () => {
        const path = workerPath({ isDevelopment: true, execPath: process.execPath, platform: process.platform })

        const run = Bun.spawn([path, '--help'], { stdin: 'ignore', stdout: 'pipe', stderr: 'pipe' })

        expect(await run.exited).toBe(2)
        expect(await new Response(run.stdout).text()).toBe('')
        expect(await new Response(run.stderr).text()).toContain('Use hog instead')
    })
})
