import { settleBeforeAbortEvenWhileCredentialsStall } from './attachment-store'
import {
    InFlightLimits,
    InFlightRegistry,
    MachineMemory,
    deferralDelayMs,
    estimateSend,
    inFlightLimitsFor,
} from './in-flight-registry'

const MIB = 1024 * 1024
const GIB = 1024 * MIB

const pending = (): { promise: Promise<void>; resolve: () => void } => {
    let resolve!: () => void
    const promise = new Promise<void>((done) => (resolve = done))
    return { promise, resolve }
}

describe('InFlightRegistry', () => {
    const roomFor = (sends: number, fileBytes: number): InFlightLimits => ({
        budgetBytes: sends * estimateSend(fileBytes).reservedBytes,
        heapLimitBytes: 64 * GIB,
        maxInFlight: 100,
    })

    it.each([
        ['the in-flight cap is reached', { ...roomFor(5, MIB), maxInFlight: 1 }, () => 0, 'at_cap'],
        ['the reservation would pass the budget', roomFor(1, MIB), () => 0, 'over_budget'],
        [
            'the heap share would pass the heap limit minus the heap in use',
            { ...roomFor(5, MIB), heapLimitBytes: 2 * estimateSend(MIB).heapBytes },
            () => estimateSend(MIB).heapBytes / 2,
            'over_heap',
        ],
    ])('defers a second send when %s, and admits it once the first ends', async (_, limits, heapUsed, reason) => {
        const registry = new InFlightRegistry(limits, heapUsed)
        const first = pending()

        const started = registry.tryStart(MIB, () => first.promise)
        expect(registry.tryStart(MIB, () => Promise.resolve())).toEqual({ deferred: reason })
        first.resolve()
        await (started as { started: Promise<void> }).started

        expect(registry.tryStart(MIB, () => Promise.resolve())).toHaveProperty('started')
    })

    it('defers every send when the worker refused sends with files', () => {
        expect(new InFlightRegistry(null).tryStart(1, () => Promise.resolve())).toEqual({ deferred: 'refused' })
    })

    it.each([
        [
            'its deadline passed',
            (deadline: AbortController, call: Promise<void>): Promise<unknown> => {
                const loading = settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, call)
                deadline.abort(new Error('deadline'))
                return loading
            },
        ],
        [
            'another file of the send failed',
            (deadline: AbortController, call: Promise<void>): Promise<unknown> =>
                Promise.all([
                    settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, call),
                    settleBeforeAbortEvenWhileCredentialsStall(deadline.signal, Promise.reject(new Error('missing'))),
                ]),
        ],
    ])(
        'keeps the reservation of a send that stopped waiting because %s, until the call settles',
        async (_, abandon) => {
            const registry = new InFlightRegistry(roomFor(1, MIB))
            const download = pending()

            const { started } = registry.tryStart(MIB, () =>
                abandon(new AbortController(), download.promise).catch(() => undefined)
            ) as { started: Promise<unknown> }
            await started
            expect(registry.tryStart(MIB, () => Promise.resolve())).toEqual({ deferred: 'over_budget' })
            download.resolve()
            await new Promise(setImmediate)
            expect(registry.tryStart(MIB, () => Promise.resolve())).toHaveProperty('started')
        }
    )
})

describe('inFlightLimitsFor', () => {
    const settings = {
        memoryFraction: 0.5,
        maxInFlight: 4,
        heartbeatIntervalMs: 10_000,
        attachmentStoreBucket: 'files',
    }
    const machine = (overrides: Partial<MachineMemory> = {}): MachineMemory => ({
        constrainedBytes: 4 * GIB,
        totalBytes: 64 * GIB,
        heapLimitBytes: 4 * GIB,
        ...overrides,
    })

    it.each([
        ['the container limit', machine(), 0.5 * (4 * GIB - 512 * MIB)],
        [
            'the machine memory when Node reports no limit as 0',
            machine({ constrainedBytes: 0 }),
            0.5 * (64 * GIB - 512 * MIB),
        ],
        [
            'the machine memory when Node reports no limit as a value past it',
            machine({ constrainedBytes: 2 ** 64 }),
            0.5 * (64 * GIB - 512 * MIB),
        ],
    ])('sizes the budget from %s', (_, memory, budgetBytes) => {
        expect(inFlightLimitsFor(settings, memory)).toEqual({
            limits: { budgetBytes, heapLimitBytes: 4 * GIB, maxInFlight: 4 },
        })
    })

    it.each([
        ['the heartbeat is off', { ...settings, heartbeatIntervalMs: 0 }, machine(), 'heartbeat is off'],
        ['the budget cannot hold one message', settings, machine({ constrainedBytes: 768 * MIB }), 'memory budget'],
        ['the heap cannot hold one message', settings, machine({ heapLimitBytes: 64 * MIB }), 'heap limit'],
        ['the cap is zero', { ...settings, maxInFlight: 0 }, machine(), 'cap'],
        ['no attachment store is set', { ...settings, attachmentStoreBucket: '' }, machine(), 'attachment store'],
    ])('refuses sends with files when %s', (_, given, memory, reason) => {
        expect(inFlightLimitsFor(given, memory)).toEqual({ refusal: expect.stringContaining(reason) })
    })
})

describe('deferralDelayMs', () => {
    it.each([
        [0, 0, 5_000],
        [0, 1, 5_000],
        [1, 0, 5_000],
        [1, 1, 10_000],
        [3, 0, 20_000],
        [3, 1, 40_000],
        [10, 0, 60_000],
        [10, 1, 120_000],
    ])(
        'waits between half and all of a doubling delay after %i deferrals (random %d): %i ms',
        (earlier, random, ms) => {
            expect(deferralDelayMs(earlier, () => random)).toBe(ms)
        }
    )
})
