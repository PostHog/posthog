import { RustExecResult } from './rust-vm'
import { RustVmBatchScheduler } from './rust-vm-batch-scheduler'

const execResult = (overrides: Partial<RustExecResult> = {}): RustExecResult => ({
    result: 'ok',
    durationUs: 100,
    logs: [],
    logsTruncated: false,
    ...overrides,
})

describe('RustVmBatchScheduler', () => {
    let runBatch: jest.Mock

    beforeEach(() => {
        runBatch = jest.fn((_program: unknown[], events: unknown[]) =>
            Promise.resolve(events.map((_, index) => execResult({ result: `result-${index}` })))
        )
    })

    it.each([
        ['one array instance', (bytecode: unknown[]) => bytecode],
        // Each team's hog function holds its own array of the same template bytecode.
        ['distinct array instances with equal content', (bytecode: unknown[]) => [...bytecode]],
    ])(
        'coalesces same-program executions from one tick into a single call, mapping results back in order (%s)',
        async (_label, instance) => {
            const scheduler = new RustVmBatchScheduler(runBatch)
            const bytecode = ['_H', 1, 38]

            const results = await Promise.all([
                scheduler.execute(instance(bytecode), { event: 'a' }),
                scheduler.execute(instance(bytecode), { event: 'b' }),
                scheduler.execute(instance(bytecode), { event: 'c' }),
            ])

            expect(runBatch).toHaveBeenCalledTimes(1)
            expect(runBatch).toHaveBeenCalledWith(bytecode, [{ event: 'a' }, { event: 'b' }, { event: 'c' }])
            expect(results.map((r) => r.result)).toEqual(['result-0', 'result-1', 'result-2'])
        }
    )

    it('keeps different programs in separate batches', async () => {
        const scheduler = new RustVmBatchScheduler(runBatch)
        const programA = ['_H', 1, 38]
        const programB = ['_H', 1, 35, 38]

        await Promise.all([
            scheduler.execute(programA, { event: 'a' }),
            scheduler.execute(programB, { event: 'b' }),
            scheduler.execute(programA, { event: 'c' }),
        ])

        expect(runBatch).toHaveBeenCalledTimes(2)
        expect(runBatch).toHaveBeenCalledWith(programA, [{ event: 'a' }, { event: 'c' }])
        expect(runBatch).toHaveBeenCalledWith(programB, [{ event: 'b' }])
    })

    it('dispatches a full queue immediately instead of letting it grow past the batch size cap', async () => {
        const scheduler = new RustVmBatchScheduler(runBatch, 2)
        const bytecode = ['_H', 1, 38]

        await Promise.all([
            scheduler.execute(bytecode, { event: 'a' }),
            scheduler.execute(bytecode, { event: 'b' }),
            scheduler.execute(bytecode, { event: 'c' }),
        ])

        expect(runBatch).toHaveBeenCalledTimes(2)
        expect(runBatch).toHaveBeenCalledWith(bytecode, [{ event: 'a' }, { event: 'b' }])
        expect(runBatch).toHaveBeenCalledWith(bytecode, [{ event: 'c' }])
    })

    it('executions enqueued after a flush go into the next batch', async () => {
        const scheduler = new RustVmBatchScheduler(runBatch)
        const bytecode = ['_H', 1, 38]

        await scheduler.execute(bytecode, { event: 'a' })
        await scheduler.execute(bytecode, { event: 'b' })

        expect(runBatch).toHaveBeenCalledTimes(2)
    })

    it('a batch-level failure rejects every waiter in that batch, not just one', async () => {
        runBatch.mockRejectedValue(new Error('addon exploded'))
        const scheduler = new RustVmBatchScheduler(runBatch)
        const bytecode = ['_H', 1, 38]

        const outcomes = await Promise.allSettled([
            scheduler.execute(bytecode, { event: 'a' }),
            scheduler.execute(bytecode, { event: 'b' }),
        ])

        expect(outcomes.map((o) => o.status)).toEqual(['rejected', 'rejected'])
    })

    it('rejects all waiters when the batch returns the wrong number of results', async () => {
        runBatch.mockResolvedValue([execResult()])
        const scheduler = new RustVmBatchScheduler(runBatch)
        const bytecode = ['_H', 1, 38]

        const outcomes = await Promise.allSettled([
            scheduler.execute(bytecode, { event: 'a' }),
            scheduler.execute(bytecode, { event: 'b' }),
        ])

        expect(outcomes.map((o) => o.status)).toEqual(['rejected', 'rejected'])
    })
})
