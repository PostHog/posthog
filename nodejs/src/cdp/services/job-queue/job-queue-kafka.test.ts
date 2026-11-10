import { Message } from 'node-rdkafka'

import { createKafkaConsumer } from '~/common/kafka/consumer'
import { EachBatch } from '~/common/kafka/consumer/consumer-v2'
import { logger } from '~/common/utils/logger'

import { CyclotronJobQueueKafka, migrateKafkaCyclotronInvocation } from './job-queue-kafka'

jest.mock('~/common/kafka/consumer', () => ({
    ...jest.requireActual('~/common/kafka/consumer'),
    createKafkaConsumer: jest.fn(),
}))

describe('CyclotronJobQueueKafka', () => {
    describe('when a batch fails', () => {
        const message = (
            value: Buffer | null,
            partition: number,
            offset: number,
            teamId: string,
            functionId: string
        ): Message => ({
            topic: 'cdp_cyclotron_hog',
            partition,
            offset,
            value,
            size: 0,
            headers: [{ teamId: Buffer.from(teamId) }, { functionId: Buffer.from(functionId) }],
        })

        const startQueue = async (backgroundTask: () => Promise<unknown>): Promise<EachBatch> => {
            let eachBatch: EachBatch | undefined
            jest.mocked(createKafkaConsumer).mockReturnValue({
                connect: (callback: EachBatch) => {
                    eachBatch = callback
                    return Promise.resolve()
                },
            } as any)
            const queue = new CyclotronJobQueueKafka(
                undefined,
                { CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: false, CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '' },
                500
            )
            await queue.startAsConsumer('hog', () => Promise.resolve({ backgroundTask: backgroundTask() }))
            return eachBatch!
        }

        const runBatch = async (eachBatch: EachBatch, messages: Message[], settle: () => void): Promise<void> => {
            const result = await eachBatch(messages)
            // The consumer drops the messages before the background task settles, so the log must not need them.
            messages.length = 0
            settle()
            await result?.backgroundTask
        }

        it.each([
            {
                stage: 'batch',
                value: null,
                backgroundTaskFails: false,
                error: 'Bad message',
            },
            {
                stage: 'background_task',
                value: Buffer.from(JSON.stringify({ id: 'inv', teamId: 1, functionId: 'fn-a', queue: 'hog' })),
                backgroundTaskFails: true,
                error: 'background task failed',
            },
        ])('logs the $stage failure with its partitions, offsets and functions and rethrows it', async (c) => {
            let settle = (): void => {}
            const backgroundTask = new Promise<void>((resolve, reject) => {
                settle = c.backgroundTaskFails ? () => reject(new Error('background task failed')) : resolve
            })
            const eachBatch = await startQueue(() => backgroundTask)
            const loggerError = jest.spyOn(logger, 'error')
            const messages = [
                message(c.value, 7, 120, '2', 'fn-b'),
                message(c.value, 3, 41, '1', 'fn-a'),
                message(c.value, 7, 118, '2', 'fn-b'),
                message(c.value, 7, 119, '1', 'fn-a'),
            ]

            await expect(runBatch(eachBatch, messages, settle)).rejects.toThrow(c.error)

            expect(loggerError).toHaveBeenCalledWith('🔄', 'cdp_cyclotron_kafka_batch_failed', {
                stage: c.stage,
                error: expect.stringContaining(c.error),
                topic: 'cdp_cyclotron_hog',
                partitions: [
                    { partition: 3, firstOffset: 41, lastOffset: 41, messages: 1 },
                    { partition: 7, firstOffset: 118, lastOffset: 120, messages: 3 },
                ],
                functions: ['1:fn-a', '2:fn-b'],
            })
        })
    })

    describe('migrateKafkaCyclotronInvocation', () => {
        // Pulled from a real job in kafka
        const legacyFormat = {
            id: '01971158-5dd2-0000-2dde-9d3478269401',
            globals: {
                event: { event: 'foo' },
            },
            teamId: 1,
            queue: 'hog',
            queuePriority: 0,
            timings: [
                {
                    kind: 'hog',
                    duration_ms: 0.6164590120315552,
                },
            ],
            hogFunctionId: '0196a6b9-1104-0000-f099-9cf11985a307',
            vmState: {
                bytecodes: {},
                stack: [],
                upvalues: [],
            },
            queueParameters: {
                response: {
                    status: 200,
                    headers: {
                        'access-control-allow-origin': '*',
                        'content-type': 'text/plain',
                        date: 'Tue, 27 May 2025 10:45:04 GMT',
                        'content-length': '0',
                    },
                },
                body: '',
                timings: [
                    {
                        kind: 'async_function',
                        duration_ms: 2429.0499999523163,
                    },
                ],
            },
        }

        it('should convert to the current format', () => {
            const invocation = migrateKafkaCyclotronInvocation(legacyFormat as any)

            expect(invocation).toMatchInlineSnapshot(`
                {
                  "functionId": "0196a6b9-1104-0000-f099-9cf11985a307",
                  "id": "01971158-5dd2-0000-2dde-9d3478269401",
                  "queue": "hog",
                  "queueParameters": {
                    "body": "",
                    "response": {
                      "headers": {
                        "access-control-allow-origin": "*",
                        "content-length": "0",
                        "content-type": "text/plain",
                        "date": "Tue, 27 May 2025 10:45:04 GMT",
                      },
                      "status": 200,
                    },
                    "timings": [
                      {
                        "duration_ms": 2429.0499999523163,
                        "kind": "async_function",
                      },
                    ],
                  },
                  "queuePriority": 0,
                  "state": {
                    "globals": {
                      "event": {
                        "event": "foo",
                      },
                    },
                    "timings": [
                      {
                        "duration_ms": 0.6164590120315552,
                        "kind": "hog",
                      },
                    ],
                    "vmState": {
                      "bytecodes": {},
                      "stack": [],
                      "upvalues": [],
                    },
                  },
                  "teamId": 1,
                }
            `)
        })
    })
})
