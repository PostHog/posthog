import { BatchStages } from './batch-stages'
import { SessionRecordingIngesterMetrics } from './metrics'

describe('BatchStages', () => {
    function gate(): { promise: Promise<void>; release: () => void } {
        let release!: () => void
        const promise = new Promise<void>((resolve) => (release = resolve))
        return { promise, release }
    }

    async function until(condition: () => boolean): Promise<void> {
        for (let i = 0; i < 1000 && !condition(); i++) {
            await new Promise(setImmediate)
        }
        if (!condition()) {
            throw new Error('condition not reached')
        }
    }

    /** Settles to the resolved value or the rejection reason, so an expected failure is never an unhandled rejection. */
    function settled<T>(promise: Promise<T>): Promise<T | unknown> {
        return promise.then(
            (value) => value,
            (error) => error
        )
    }

    it('lets the next batch into an earlier stage while the current batch holds a later one, and never two batches into one stage', async () => {
        const stages = new BatchStages(['load', 'process'])
        const events: string[] = []
        const holdLoadOfFirst = gate()
        const holdProcessOfFirst = gate()
        const run = (id: number, holdLoad?: Promise<void>, holdProcess?: Promise<void>): Promise<number> =>
            stages
                .admit()
                .stage('load', async () => {
                    events.push(`load ${id}`)
                    await holdLoad
                    return id
                })
                .stage('process', async (loaded) => {
                    events.push(`process ${id} start`)
                    await holdProcess
                    events.push(`process ${id} end`)
                    return loaded
                })
                .done()

        const first = run(1, holdLoadOfFirst.promise, holdProcessOfFirst.promise)
        const second = run(2)
        await until(() => events.includes('load 1'))
        await new Promise(setImmediate)
        expect(events).toEqual(['load 1'])

        holdLoadOfFirst.release()
        await until(() => events.includes('load 2') && events.includes('process 1 start'))
        await new Promise(setImmediate)
        expect(events).not.toContain('process 2 start')

        holdProcessOfFirst.release()
        await expect(Promise.all([first, second])).resolves.toEqual([1, 2])
        expect(events.filter((event) => event.startsWith('process'))).toEqual([
            'process 1 start',
            'process 1 end',
            'process 2 start',
            'process 2 end',
        ])
    })

    it('stops the batches in flight behind a failed one at their next stage, lets the batch ahead finish, and admits new batches after it', async () => {
        const stages = new BatchStages(['load', 'process'])
        const holdProcessOfFirst = gate()
        let secondLoadFailed = false
        const loaded = new Set<number>()
        const admitAfter = (id: number): Promise<unknown> =>
            settled(
                stages
                    .admit()
                    .stage('load', () => {
                        loaded.add(id)
                        return Promise.resolve()
                    })
                    .stage('process', () => Promise.resolve())
                    .done()
            )

        const first = stages
            .admit()
            .stage('load', () => Promise.resolve())
            .stage('process', () => holdProcessOfFirst.promise)
            .done()
        const second = settled(
            stages
                .admit()
                .stage('load', () => {
                    secondLoadFailed = true
                    return Promise.reject(new Error('broken'))
                })
                .stage('process', () => Promise.resolve())
                .done()
        )
        const third = admitAfter(3)

        await until(() => secondLoadFailed)
        await new Promise(setImmediate)
        expect(loaded.size).toBe(0)

        // The rejections surface through the process stage, which sits behind the first batch until it is released.
        holdProcessOfFirst.release()
        await expect(first).resolves.toBeUndefined()
        await expect(second).resolves.toEqual(new Error('broken'))
        await expect(third).resolves.toEqual(new Error('broken'))
        expect(loaded.size).toBe(0)

        // Whether to admit anything after a failure is the consumer's call, so a batch admitted afterwards runs.
        await expect(admitAfter(4)).resolves.toBeUndefined()
        expect(loaded).toEqual(new Set([4]))
    })

    it('stops a later batch at its next stage when an earlier batch fails in a later stage while the later batch is mid-stage', async () => {
        const stages = new BatchStages(['load', 'process'])
        const holdLoadOfSecond = gate()
        let secondProcessed = false

        const first = settled(
            stages
                .admit()
                .stage('load', () => Promise.resolve())
                .stage('process', () => {
                    throw new Error('broken in process')
                })
                .done()
        )
        const second = settled(
            stages
                .admit()
                .stage('load', () => holdLoadOfSecond.promise)
                .stage('process', () => {
                    secondProcessed = true
                    return Promise.resolve()
                })
                .done()
        )

        await expect(first).resolves.toEqual(new Error('broken in process'))
        holdLoadOfSecond.release()
        await expect(second).resolves.toEqual(new Error('broken in process'))
        expect(secondProcessed).toBe(false)
    })

    it('records a wait and a duration for every stage of every batch', async () => {
        const stages = new BatchStages(['load', 'process'])
        const countOf = async (metric: string, stage: string): Promise<number> => {
            const collected = await (SessionRecordingIngesterMetrics as any)[metric].get()
            return collected.values.find(
                (v: { metricName: string; labels: { stage: string } }) =>
                    v.metricName.endsWith('_count') && v.labels.stage === stage
            )?.value as number
        }
        const before = await countOf('batchStageDuration', 'process')
        const waitBefore = await countOf('batchStageWait', 'load')

        await stages
            .admit()
            .stage('load', () => Promise.resolve())
            .stage('process', () => Promise.resolve())
            .done()

        expect(await countOf('batchStageDuration', 'process')).toBe((before ?? 0) + 1)
        expect(await countOf('batchStageWait', 'load')).toBe((waitBefore ?? 0) + 1)
    })

    it.each([
        ['two stages with the same name', () => new BatchStages(['load', 'load']), 'unique stage names'],
        ['no stages', () => new BatchStages([]), 'at least one stage'],
        [
            'a stage entered out of the declared order',
            () => new BatchStages(['load', 'process']).admit().stage('process', () => Promise.resolve()),
            "stage 0 is 'load'",
        ],
        [
            'a stage entered past the last one',
            () =>
                new BatchStages(['load'])
                    .admit()
                    .stage('load', () => Promise.resolve())
                    .stage('load', () => Promise.resolve()),
            "stage 1 is 'none'",
        ],
    ])('rejects %s', (_case, build, message) => {
        expect(build).toThrow(message)
    })

    it('rejects a batch that finishes before its last stage', async () => {
        const stages = new BatchStages(['load', 'process'])
        await expect(
            stages
                .admit()
                .stage('load', () => Promise.resolve())
                .done()
        ).rejects.toThrow("after 1 of 2 stages, before 'process'")
    })

    it('rejects a stage queued after the tick that admitted the batch, because a later batch could enter it first', async () => {
        const stages = new BatchStages(['load'])
        const batch = stages.admit()
        await Promise.resolve()
        expect(() => batch.stage('load', () => Promise.resolve())).toThrow('after the tick that admitted it')
    })
})
