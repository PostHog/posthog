import type { Aws } from '../cloud/aws'
import type { RunManifest } from '../cloud/lease'
import { writerCpuOf } from './writer-cpu'

const T = Date.UTC(2026, 0, 5, 10, 0, 0)
const MINUTE = 60_000
const MANIFEST: RunManifest = {
    runId: 'run-1',
    account: '111111111111',
    expiresAt: new Date(T + 6 * 60 * MINUTE).toISOString(),
    stackName: 'scenario-run-1',
}

const publishingAfter = (lagMs: number): Aws => ({
    call: (args) => {
        const [from, to] = ['--start-time', '--end-time'].map((flag) => Date.parse(args[args.indexOf(flag) + 1]))
        const published = Array.from({ length: (to - from) / MINUTE }, (_, i) => from + i * MINUTE).filter(
            (minute) => minute + MINUTE + lagMs <= Date.now()
        )
        return Promise.resolve({
            MetricDataResults: [
                {
                    Timestamps: published.map((minute) => new Date(minute).toISOString()),
                    Values: published.map(() => 50),
                    StatusCode: 'Complete',
                },
            ],
        })
    },
    text: () => Promise.reject(new Error('the CPU read only calls')),
})

describe('writerCpuOf', () => {
    beforeEach(() => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        jest.setSystemTime(T + 2 * MINUTE + 10_000)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each<[string, number, number[]]>([
        ['waits for CloudWatch to publish the last whole minute of the drive', 2 * MINUTE, [0, 1]],
        ['stops waiting once CloudWatch has held back the last minute past its deadline', 60 * MINUTE, []],
    ])('%s', async (_story, lagMs, minutes) => {
        const read = writerCpuOf(publishingAfter(lagMs), MANIFEST, {
            startedAt: T,
            endedAt: T + 2 * MINUTE + 5_000,
        })

        await jest.advanceTimersByTimeAsync(10 * MINUTE)

        await expect(read).resolves.toEqual(minutes.map((minute) => ({ at: T + minute * MINUTE, percent: 50 })))
    })

    it('stops waiting for a CloudWatch read that has not answered by the deadline', async () => {
        let settled = false
        const read = writerCpuOf(
            {
                call: (_args, signal) =>
                    new Promise((_resolve, reject) =>
                        signal?.addEventListener('abort', () => reject(new Error('aws cloudwatch was cancelled')))
                    ),
                text: () => Promise.reject(new Error('the CPU read only calls')),
            },
            MANIFEST,
            { startedAt: T, endedAt: T + 2 * MINUTE + 5_000 }
        ).finally(() => (settled = true))

        await jest.advanceTimersByTimeAsync(5 * MINUTE)

        expect(settled).toBe(true)
        await expect(read).resolves.toEqual([])
    })

    it('fails a CloudWatch read that comes back incomplete before the deadline', async () => {
        const read = writerCpuOf(
            {
                call: () =>
                    Promise.resolve({
                        MetricDataResults: [{ Timestamps: [], Values: [], StatusCode: 'PartialData' }],
                    }),
                text: () => Promise.reject(new Error('the CPU read only calls')),
            },
            MANIFEST,
            { startedAt: T, endedAt: T + 2 * MINUTE + 5_000 }
        )
        const failed = expect(read).rejects.toThrow('the writer CPU read came back PartialData, not Complete')

        await jest.advanceTimersByTimeAsync(10 * MINUTE)

        await failed
    })

    it('stops waiting for CloudWatch when the run is interrupted while a read is in flight', async () => {
        const interrupted = new AbortController()
        const aws = publishingAfter(60 * MINUTE)
        let settled = false
        const read = writerCpuOf(
            {
                ...aws,
                call: (args) => {
                    interrupted.abort()
                    return aws.call(args)
                },
            },
            MANIFEST,
            { startedAt: T, endedAt: T + 2 * MINUTE + 5_000 },
            interrupted.signal
        ).finally(() => (settled = true))

        await jest.advanceTimersByTimeAsync(0)

        expect(settled).toBe(true)
        await expect(read).resolves.toEqual([])
    })

    it('stops waiting for CloudWatch once the run is interrupted', async () => {
        const interrupted = new AbortController()
        let settled = false
        const read = writerCpuOf(
            publishingAfter(60 * MINUTE),
            MANIFEST,
            { startedAt: T, endedAt: T + 2 * MINUTE + 5_000 },
            interrupted.signal
        ).finally(() => (settled = true))
        await jest.advanceTimersByTimeAsync(MINUTE)

        interrupted.abort()
        await jest.advanceTimersByTimeAsync(0)

        expect(settled).toBe(true)
        await expect(read).resolves.toEqual([])
    })
})
