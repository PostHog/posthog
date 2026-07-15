import { TopicPartitionOffset } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { ReplayRecordRow } from './pipeline-types'
import { createCommitOffsetsStep } from './session-batch-commit-offsets-step'

describe('createCommitOffsetsStep', () => {
    let committed: TopicPartitionOffset[][]
    let offsetManager: KafkaOffsetManager
    let promiseScheduler: PromiseScheduler

    const row = (partition: number, offset: number, recorded = true) => ({
        type: PipelineResultType.OK as const,
        value: { partition, offset, recorded } satisfies ReplayRecordRow,
        sideEffects: [],
        warnings: [],
    })

    beforeEach(() => {
        committed = []
        offsetManager = new KafkaOffsetManager((offsets) => {
            committed.push(offsets)
            return Promise.resolve()
        }, 'test-topic')
        promiseScheduler = new PromiseScheduler()
    })

    it('commits the highest offset per partition from the accumulated rows, dropped ones included', async () => {
        const step = createCommitOffsetsStep(offsetManager, promiseScheduler)

        const input = {
            elements: [row(0, 1), row(0, 2, false), row(1, 10), row(0, 3, false), row(1, 9)],
        }
        const result = await step(input)

        expect(isOkResult(result) ? result.value : null).toBe(input)
        // The dropped rows at offsets 2-3 advance partition 0 past the last recorded offset.
        expect(committed).toEqual([
            [
                { topic: 'test-topic', partition: 0, offset: 4 },
                { topic: 'test-topic', partition: 1, offset: 11 },
            ],
        ])
    })

    it('awaits in-flight produces before committing the offsets that cover them', async () => {
        const order: string[] = []
        let settleProduce: (() => void) | null = null
        void promiseScheduler.schedule(
            new Promise<void>((resolve) => {
                settleProduce = () => {
                    order.push('produce-settled')
                    resolve()
                }
            })
        )
        const step = createCommitOffsetsStep(
            new KafkaOffsetManager((offsets) => {
                order.push('committed')
                committed.push(offsets)
                return Promise.resolve()
            }, 'test-topic'),
            promiseScheduler
        )

        const stepPromise = step({ elements: [row(0, 1)] })
        // The step is parked on the scheduler until the produce settles.
        await new Promise((resolve) => setImmediate(resolve))
        expect(order).toEqual([])
        settleProduce!()
        await stepPromise

        expect(order).toEqual(['produce-settled', 'committed'])
    })

    it('commits nothing for an empty cycle', async () => {
        const step = createCommitOffsetsStep(offsetManager, promiseScheduler)

        await step({ elements: [] })

        expect(committed).toEqual([])
    })
})
