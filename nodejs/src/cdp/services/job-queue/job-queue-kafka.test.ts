import { Message } from 'node-rdkafka'

import { migrateKafkaCyclotronInvocation } from './job-queue-kafka'

// Mock node-rdkafka so we can control the seek test consumer
const mockConsume = jest.fn()
const mockAssign = jest.fn()
const mockConnect = jest.fn()
const mockDisconnect = jest.fn()
const mockSetDefaultConsumeTimeout = jest.fn()
const mockIsConnected = jest.fn().mockReturnValue(true)

jest.mock('node-rdkafka', () => {
    const actual = jest.requireActual('node-rdkafka')
    return {
        ...actual,
        KafkaConsumer: jest.fn().mockImplementation(() => ({
            consume: mockConsume,
            assign: mockAssign,
            connect: mockConnect,
            disconnect: mockDisconnect,
            setDefaultConsumeTimeout: mockSetDefaultConsumeTimeout,
            isConnected: mockIsConnected,
        })),
    }
})

jest.mock('../../../kafka/producer', () => ({
    KafkaProducerWrapper: { create: jest.fn() },
}))

jest.mock('../../../kafka/consumer', () => ({
    KafkaConsumer: jest.fn(),
}))

describe('CyclotronJobQueue - kafka', () => {
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

    describe('testSeekLatency', () => {
        let queue: any

        beforeEach(() => {
            jest.clearAllMocks()
            mockConnect.mockImplementation((_opts: any, cb: any) => cb(null, {}))

            const { CyclotronJobQueueKafka } = require('./job-queue-kafka')
            queue = new CyclotronJobQueueKafka(
                {
                    CDP_CYCLOTRON_TEST_SEEK_LATENCY: true,
                    CDP_CYCLOTRON_TEST_SEEK_SAMPLE_RATE: 1.0,
                    CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: false,
                },
                'hog',
                jest.fn().mockResolvedValue({ backgroundTask: Promise.resolve() })
            )
        })

        const makeMessage = (partition: number, offset: number): Message => ({
            topic: 'cdp_cyclotron_hog',
            partition,
            offset,
            value: Buffer.from(JSON.stringify({ id: 'test', teamId: 1, functionId: 'f1', queue: 'hog' })),
            size: 100,
            timestamp: Date.now(),
        })

        it('should assign to a random older offset and consume one message', async () => {
            const mockMessage = {
                value: Buffer.from('test'),
                offset: 500_000,
                partition: 3,
                topic: 'cdp_cyclotron_hog',
            }
            mockConsume.mockImplementation((_count: number, cb: any) => cb(null, [mockMessage]))

            await queue['testSeekLatency'](makeMessage(3, 1_000_000))

            expect(mockAssign).toHaveBeenCalledTimes(1)
            const assignment = mockAssign.mock.calls[0][0][0]
            expect(assignment.topic).toBe('cdp_cyclotron_hog')
            expect(assignment.partition).toBe(3)
            expect(assignment.offset).toBeGreaterThanOrEqual(0)
            expect(assignment.offset).toBeLessThan(1_000_000)

            expect(mockConsume).toHaveBeenCalledWith(1, expect.any(Function))
        })

        it('should skip messages with offset 0', async () => {
            await queue['testSeekLatency'](makeMessage(0, 0))

            expect(mockAssign).not.toHaveBeenCalled()
            expect(mockConsume).not.toHaveBeenCalled()
        })

        it('should cap seek-back at 50M offsets', async () => {
            const mockMessage = {
                value: Buffer.from('test'),
                offset: 40_000_000,
                partition: 0,
                topic: 'cdp_cyclotron_hog',
            }
            mockConsume.mockImplementation((_count: number, cb: any) => cb(null, [mockMessage]))

            await queue['testSeekLatency'](makeMessage(0, 100_000_000))

            const assignment = mockAssign.mock.calls[0][0][0]
            expect(assignment.offset).toBeGreaterThanOrEqual(100_000_000 - 50_000_000)
            expect(assignment.offset).toBeLessThan(100_000_000)
        })

        it('should handle consume errors gracefully', async () => {
            mockConsume.mockImplementation((_count: number, cb: any) => cb(new Error('broker unavailable'), []))

            await expect(queue['testSeekLatency'](makeMessage(0, 1000))).resolves.not.toThrow()
        })

        it('should handle empty consume result', async () => {
            mockConsume.mockImplementation((_count: number, cb: any) => cb(null, []))

            await expect(queue['testSeekLatency'](makeMessage(0, 1000))).resolves.not.toThrow()
        })
    })
})
