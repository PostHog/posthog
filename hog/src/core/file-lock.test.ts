import { describe, expect, test } from 'bun:test'

import { fakeRuntime } from '@/testing'

import { withFileLock } from './file-lock'

describe('withFileLock', () => {
    test('a process that holds the lock past the stale limit keeps it while it works', async () => {
        const runtime = fakeRuntime()
        const finished: string[] = []

        const first = withFileLock(runtime, 'test.lock', async () => {
            await runtime.sleep(300_000)
            finished.push('first')
        })
        await runtime.sleep(1_000)
        const second = withFileLock(runtime, 'test.lock', async () => {
            finished.push('second')
        })
        await Promise.all([first, second])

        expect(finished).toEqual(['first', 'second'])
        expect(runtime.files['/home/test/.config/hog/test.lock']).toBeUndefined()
    })
})
