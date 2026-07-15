import { TopicPartitionOffset } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { isOkResult } from '~/ingestion/framework/results'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { createCommitOffsetsStep } from './session-batch-commit-offsets-step'

describe('createCommitOffsetsStep', () => {
    let committed: TopicPartitionOffset[][]
    let promiseScheduler: PromiseScheduler

    function createOffsetManager(onCommit?: () => void): KafkaOffsetManager {
        return new KafkaOffsetManager((offsets) => {
            onCommit?.()
            committed.push(offsets)
            return Promise.resolve()
        }, 'test-topic')
    }

    beforeEach(() => {
        committed = []
        promiseScheduler = new PromiseScheduler()
    })

    it('commits the next offset per partition from the reduced cycle state', async () => {
        const step = createCommitOffsetsStep(createOffsetManager(), promiseScheduler)

        const input = {
            state: {
                offsets: new Map([
                    [0, 3],
                    [1, 10],
                ]),
            },
        }
        const result = await step(input)

        expect(isOkResult(result) ? result.value : null).toBe(input)
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
            createOffsetManager(() => order.push('committed')),
            promiseScheduler
        )

        const stepPromise = step({ state: { offsets: new Map([[0, 1]]) } })
        // The step is parked on the scheduler until the produce settles.
        await new Promise((resolve) => setImmediate(resolve))
        expect(order).toEqual([])
        settleProduce!()
        await stepPromise

        expect(order).toEqual(['produce-settled', 'committed'])
    })

    it('commits nothing for an empty cycle', async () => {
        const step = createCommitOffsetsStep(createOffsetManager(), promiseScheduler)

        await step({ state: { offsets: new Map() } })

        expect(committed).toEqual([])
    })
})
