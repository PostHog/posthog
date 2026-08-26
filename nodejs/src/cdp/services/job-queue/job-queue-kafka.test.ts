import { UnknownTopicError } from '~/common/utils/db/error'

import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'
import { CyclotronJobQueueKafka, migrateKafkaCyclotronInvocation } from './job-queue-kafka'
import { UnroutableInvocationsError } from './shared'

describe('CyclotronJobQueueKafka', () => {
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

    describe('queueInvocations', () => {
        const buildQueue = (produce: jest.Mock): CyclotronJobQueueKafka => {
            const queue = new CyclotronJobQueueKafka(
                undefined,
                {
                    CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: false,
                    CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
                } as any,
                10
            )
            ;(queue as any).kafkaProducer = { produce }
            return queue
        }

        const invocation = (id: string, queue: CyclotronJobQueueKind): CyclotronJobInvocation => ({
            id,
            teamId: 1,
            functionId: 'fn-1',
            state: {},
            queue,
            queuePriority: 0,
        })

        // 'email' is served only by Postgres, so cdp_cyclotron_email exists on no cluster. Producing
        // to it must not take the worker down: that is what stalls the partition for every other
        // team, and a restart just replays the same message.
        it('reports unroutable invocations instead of throwing the produce error', async () => {
            const produce = jest.fn(({ topic }: { topic: string }) =>
                topic === 'cdp_cyclotron_email'
                    ? Promise.reject(new UnknownTopicError(topic, new Error('Broker: Unknown topic or partition')))
                    : Promise.resolve()
            )
            const queue = buildQueue(produce)

            const error = await queue
                .queueInvocations([invocation('a', 'hog'), invocation('b', 'email')])
                .then(() => null)
                .catch((e) => e)

            expect(error).toBeInstanceOf(UnroutableInvocationsError)
            expect(error.invocations.map((x: CyclotronJobInvocation) => x.id)).toEqual(['b'])
            // The routable job is still produced — one undeliverable job must not hold up the batch.
            expect(produce).toHaveBeenCalledTimes(2)
        })

        it('rethrows any other produce error so the batch is retried', async () => {
            const boom = new Error('broker unavailable')
            const queue = buildQueue(jest.fn(() => Promise.reject(boom)))

            await expect(queue.queueInvocations([invocation('a', 'hog')])).rejects.toBe(boom)
        })

        it('resolves when every invocation is routable', async () => {
            const queue = buildQueue(jest.fn(() => Promise.resolve()))

            await expect(queue.queueInvocations([invocation('a', 'hog')])).resolves.toBeUndefined()
        })
    })
})
