import { register } from 'prom-client'

import { ConcurrencyController } from '~/common/utils/concurrencyController'

import { ImageFetchProcessingMetrics } from './processing-metrics'

async function sample(name: string, stage: string): Promise<number | undefined> {
    const metric = await register.getSingleMetric(name)!.get()
    return metric.values.find((value) => value.labels.stage === stage)?.value
}

describe('ImageFetchProcessingMetrics', () => {
    beforeEach(() => register.resetMetrics())
    afterEach(() => jest.restoreAllMocks())

    it('keeps the oldest overlapping operation visible and removes finished stages', async () => {
        const clock = jest.spyOn(performance, 'now').mockReturnValue(1000)
        const first = ImageFetchProcessingMetrics.start('batch_fetch')
        clock.mockReturnValue(2000)
        const second = ImageFetchProcessingMetrics.start('batch_fetch')
        clock.mockReturnValue(5000)
        expect(await sample('ml_image_fetch_stage_active', 'batch_fetch')).toBe(2)
        expect(await sample('ml_image_fetch_stage_oldest_seconds', 'batch_fetch')).toBe(4)
        first.move('batch_history_write')
        expect(await sample('ml_image_fetch_stage_oldest_seconds', 'batch_fetch')).toBe(3)
        second.finish()
        second.finish()
        first.finish()
        expect(await sample('ml_image_fetch_stage_active', 'batch_fetch')).toBe(0)
        expect(await sample('ml_image_fetch_stage_oldest_seconds', 'batch_fetch')).toBe(0)
        const duration = await register.getSingleMetric('ml_image_fetch_stage_duration_seconds')!.get()
        expect(duration.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    metricName: 'ml_image_fetch_stage_duration_seconds_count',
                    labels: { stage: 'batch_fetch' },
                    value: 2,
                }),
                expect.objectContaining({
                    metricName: 'ml_image_fetch_stage_duration_seconds_sum',
                    labels: { stage: 'batch_fetch' },
                    value: 7,
                }),
            ])
        )
    })

    it('separates admission from running work and cleans up a rejected operation', async () => {
        const controller = new ConcurrencyController(1)
        let release!: () => void
        const blocked = new Promise<void>((resolve) => {
            release = resolve
        })
        const first = ImageFetchProcessingMetrics.runLimited(controller, 'candidate_admission', 'candidate_work', {
            debugTag: 'example.com',
            fn: () => blocked,
        })
        const error = new Error('synthetic failure')
        const second = ImageFetchProcessingMetrics.runLimited(controller, 'candidate_admission', 'candidate_work', {
            debugTag: 'example.org',
            fn: () => Promise.reject(error),
        })
        const rejected = expect(second).rejects.toBe(error)
        expect(await sample('ml_image_fetch_stage_active', 'candidate_admission')).toBe(1)
        expect(await sample('ml_image_fetch_stage_active', 'candidate_work')).toBe(1)
        release()
        await first
        await rejected
        expect(await sample('ml_image_fetch_stage_active', 'candidate_admission')).toBe(0)
        expect(await sample('ml_image_fetch_stage_active', 'candidate_work')).toBe(0)
        await expect(ImageFetchProcessingMetrics.measure('candidate_policy', () => Promise.reject(error))).rejects.toBe(
            error
        )
        expect(await sample('ml_image_fetch_stage_active', 'candidate_policy')).toBe(0)
    })

    it('collects live queue depths across passes and stops retaining finished queues', async () => {
        const queue = { candidateCount: 4 }
        const stopFirst = ImageFetchProcessingMetrics.trackQueue(queue)
        const stopSecond = ImageFetchProcessingMetrics.trackQueue({ candidateCount: 2 })
        const metric = register.getSingleMetric('ml_image_fetch_candidates_queued')!
        expect((await metric.get()).values[0].value).toBe(6)
        queue.candidateCount = 1
        expect((await metric.get()).values[0].value).toBe(3)
        stopFirst()
        stopSecond()
        expect((await metric.get()).values[0].value).toBe(0)
    })
})
