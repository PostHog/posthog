import { describe, expect, test } from 'bun:test'

import { COMMANDS } from '@/commands'
import { fakeRuntime } from '@/testing'

import { resumeApproval, type ApprovalFlow, type PendingApproval, type PollOutcome } from './approval'
import { Context } from './context'
import { HogError } from './errors'
import type { GlobalOptions } from './globals'

const PENDING_FILE = '/home/test/.config/hog/pending-thing-start.json'
const START = Date.UTC(2026, 0, 1)
const PENDING: PendingApproval = {
    url: 'https://ph.example.com/approve',
    expiresAt: START + 600_000,
    intervalSeconds: 5,
}

describe('resumeApproval', () => {
    test.each([
        [
            'polls five seconds slower after each slow_down',
            [{ state: 'slow_down' }, { state: 'slow_down' }, { state: 'pending' }, { state: 'approved', value: 'ok' }],
            'ok',
            [5_000, 15_000, 30_000, 45_000],
        ],
        ['forgets a request the person rejected', [{ state: 'rejected' }], 'thing_rejected', [5_000]],
    ] as const)('%s', async (_name, outcomes, expected, pollTimes) => {
        const runtime = fakeRuntime({ files: { [PENDING_FILE]: JSON.stringify(PENDING) } })
        const ctx = new Context(
            runtime,
            {} as GlobalOptions,
            { agent: 'test', agentReason: '', format: 'json', color: false, columns: undefined, ci: false },
            COMMANDS
        )
        const remaining: PollOutcome<string>[] = [...outcomes]
        const polledAt: number[] = []
        const flow: ApprovalFlow<PendingApproval, string> = {
            command: 'hog thing start',
            noun: 'thing',
            start: async () => PENDING,
            poll: async () => {
                polledAt.push(runtime.now() - START)
                return remaining.shift() ?? { state: 'pending' }
            },
        }

        const outcome = await resumeApproval(ctx, flow).catch((error: unknown) =>
            error instanceof HogError ? error.code : error
        )

        expect(outcome).toBe(expected)
        expect(polledAt).toEqual([...pollTimes])
        // An approval stays pending until the caller stores its value. A rejection ends it.
        expect(runtime.files[PENDING_FILE] !== undefined).toBe(expected === 'ok')
    })
})
