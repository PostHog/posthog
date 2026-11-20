import { describe, expect, test } from 'bun:test'
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Worker, WORKER_PROTOCOL } from './worker'

const EXECUTABLE = 0o755

const RELEASED = { version: '1.2.3', date: '2026-01-01T00:00:00.000Z' }
const hello = (version: string, protocol = WORKER_PROTOCOL): string =>
    `echo '{"type":"hello","protocol":${protocol},"version":"${version}"}'; cat > /dev/null`

function program(script: string, folder = ''): string {
    const path = join(mkdtempSync(join(tmpdir(), 'hog-worker-test-')), folder, 'hog-worker')
    mkdirSync(join(path, '..'), { recursive: true })
    writeFileSync(path, `#!/bin/sh\n${script}\n`)
    chmodSync(path, EXECUTABLE)
    return path
}

const detect = (path: string): Promise<unknown> =>
    new Worker(path).detect(
        [{ path: '/build/a.js', bundle: true, map: false, mapping: false, native: false }],
        undefined
    )

describe('starting hog-worker', () => {
    test.each([
        [
            'a worker from another release',
            hello('9.9.9', WORKER_PROTOCOL + 1),
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

    test.each([
        ['the same version', RELEASED.version, undefined],
        ['another version', '1.2.2', "isn't from this release of hog, 1.2.3"],
    ])('a released hog checks a worker of %s by its version', async (_name, version, message) => {
        const failure = await new Worker(program(hello(version)), RELEASED).check().catch((error: Error) => error)

        expect(failure?.message).toEqual(message === undefined ? undefined : expect.stringContaining(message))
    })

    test.each([
        ['Cellar/hog/1.2.3/bin', 'Run `brew upgrade hog`.'],
        ['lib/node_modules/@posthog/hog-linux-x64/bin', 'Run `npm install -g hog@latest`.'],
        ['bin', 'Run `hog upgrade`.'],
    ])('a mismatched worker under %s names the command of that install', async (folder, hint) => {
        const failure = await detect(program('echo hello; cat > /dev/null', folder)).catch((error: unknown) => error)

        expect(failure).toMatchObject({ hint: expect.stringContaining(hint) })
    })
})
