import { Message } from 'node-rdkafka'

import { logger } from '../../utils/logger'
import { PipelineResultType, dlq, ok } from '../pipelines/results'
import { createParseKafkaMessageStep } from './parse-kafka-message'

// Mock dependencies
jest.mock('../../../src/utils/logger')

const VALID_UUID = '123e4567-e89b-12d3-a456-426614174000'

describe('createParseKafkaMessageStep', () => {
    const mockLogger = logger as jest.Mocked<typeof logger>
    let step: ReturnType<typeof createParseKafkaMessageStep>

    beforeEach(() => {
        jest.clearAllMocks()
        step = createParseKafkaMessageStep()
    })

    describe('successful parsing', () => {
        it('should parse valid Kafka message with complete event data', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test_user',
                            team_id: 1,
                            properties: { test: 'value' },
                        }),
                        token: 'test_token',
                        ip: '127.0.0.1',
                        site_url: 'https://example.com',
                        uuid: VALID_UUID,
                        now: '2023-01-01T00:00:00Z',
                        sent_at: '2023-01-01T00:00:01Z',
                        kafka_offset: '123',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            event: 'test_event',
                            distinct_id: 'test_user',
                            team_id: 1,
                            properties: {
                                test: 'value',
                                $ip: '127.0.0.1',
                                $sent_at: '2023-01-01T00:00:01Z',
                            },
                            ip: null,
                            site_url: 'https://example.com',
                            uuid: VALID_UUID,
                            now: '2023-01-01T00:00:00Z',
                            sent_at: '2023-01-01T00:00:01Z',
                        },
                    },
                })
            )
        })

        it('should parse message with minimal event data', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'minimal_event',
                            distinct_id: 'user123',
                        }),
                        uuid: VALID_UUID,
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            event: 'minimal_event',
                            distinct_id: 'user123',
                            uuid: VALID_UUID,
                            ip: null,
                            site_url: '',
                            now: '',
                            properties: {},
                        },
                    },
                })
            )
        })

        it('should handle message with additional raw event fields', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test_user',
                        }),
                        uuid: VALID_UUID,
                        custom_field: 'custom_value',
                        another_field: 42,
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            event: 'test_event',
                            distinct_id: 'test_user',
                            uuid: VALID_UUID,
                            ip: null,
                            site_url: '',
                            now: '',
                            properties: {},
                        },
                    },
                })
            )
        })

        it('should preserve all properties from both data and raw event', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test_user',
                            properties: { inner: 'value' },
                        }),
                        properties: { outer: 'value' },
                        token: 'test_token',
                        uuid: VALID_UUID,
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            event: 'test_event',
                            distinct_id: 'test_user',
                            uuid: VALID_UUID,
                            properties: { outer: 'value' }, // This will overwrite the inner properties
                            ip: null,
                            site_url: '',
                            now: '',
                        },
                    },
                })
            )
        })

        it('should normalize event data during parsing', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test\u0000user', // with null byte
                            team_id: 1,
                            properties: { test: 'value' },
                            ip: '127.0.0.1',
                        }),
                        token: 'test\u0000token', // with null byte
                        uuid: VALID_UUID,
                        ip: '192.168.1.1',
                        sent_at: '2023-01-01T00:00:01Z',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            event: 'test_event',
                            distinct_id: 'test\uFFFDuser', // null byte replaced with replacement character
                            team_id: 1,
                            properties: {
                                test: 'value',
                                $ip: '192.168.1.1', // ip from raw event field added to properties
                                $sent_at: '2023-01-01T00:00:01Z', // sent_at added to properties
                            },
                            ip: null, // ip field set to null for safety
                            uuid: VALID_UUID,
                            site_url: '',
                            now: '',
                            sent_at: '2023-01-01T00:00:01Z',
                        },
                    },
                })
            )
        })
    })

    describe('uuid validation', () => {
        it.each([
            ['missing uuid', {}, 'empty_uuid'],
            ['null uuid', { uuid: null }, 'empty_uuid'],
            ['empty string uuid', { uuid: '' }, 'empty_uuid'],
            ['invalid format', { uuid: 'not-a-uuid' }, 'invalid_uuid'],
            ['too short', { uuid: '123e4567-e89b-12d3-a456' }, 'invalid_uuid'],
        ])('should DLQ message with %s', async (_label, uuidOverride, expectedReason) => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test_user',
                        }),
                        ...uuidOverride,
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq(expectedReason))
        })
    })

    describe('error handling', () => {
        it('should return DLQ when message value is null', async () => {
            const mockMessage: Message = {
                value: null,
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return DLQ when message value is undefined', async () => {
            const mockMessage: Message = {
                value: undefined,
            } as unknown as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return DLQ when outer JSON is invalid', async () => {
            const mockMessage: Message = {
                value: Buffer.from('invalid json'),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return DLQ when data field JSON is invalid', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: 'invalid json in data field',
                        token: 'test_token',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })
    })

    describe('type validation', () => {
        function makeMessage(
            dataOverrides: Record<string, unknown> = {},
            outerOverrides: Record<string, unknown> = {}
        ): Message {
            return {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: 'test_user',
                            ...dataOverrides,
                        }),
                        uuid: VALID_UUID,
                        ...outerOverrides,
                    })
                ),
            } as Message
        }

        describe('string fields accept strings, numbers, and booleans', () => {
            it.each([
                ['distinct_id', { distinct_id: 123 }, '123'],
                ['distinct_id', { distinct_id: true }, 'true'],
                ['event', { event: 42 }, '42'],
            ] as const)('%s coerces to string', async (field, dataOverrides, expected) => {
                const result = await step({ message: makeMessage(dataOverrides) })

                expect(result.type).toBe(PipelineResultType.OK)
                const event = (result as any).value.event.event
                expect(event[field]).toBe(expected)
            })

            it('ip with number coerces to string', async () => {
                const result = await step({ message: makeMessage({}, { ip: 10 }) })

                expect(result.type).toBe(PipelineResultType.OK)
                const event = (result as any).value.event.event
                // sanitizeEvent moves ip to properties.$ip and sets ip to null
                expect(event.properties.$ip).toBe('10')
                expect(event.ip).toBeNull()
            })
        })

        describe('string fields reject objects and arrays', () => {
            it.each([
                ['distinct_id', { distinct_id: { a: 1 } }],
                ['distinct_id', { distinct_id: [1, 2] }],
                ['event', { event: { a: 1 } }],
                ['event', { event: ['a'] }],
            ])('%s with %j should DLQ', async (_field, dataOverrides) => {
                const result = await step({ message: makeMessage(dataOverrides) })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })
        })

        describe('number fields accept numbers and numeric strings', () => {
            it.each([
                ['team_id', { team_id: '42' }, 42],
                ['team_id', { team_id: 7 }, 7],
                ['offset', { offset: '100' }, 100],
                ['offset', { offset: 0 }, 0],
            ] as const)('%s coerces to number', async (field, dataOverrides, expected) => {
                const result = await step({ message: makeMessage(dataOverrides) })

                expect(result.type).toBe(PipelineResultType.OK)
                const event = (result as any).value.event.event
                expect(event[field]).toBe(expected)
            })
        })

        describe('number fields reject non-numeric values', () => {
            it.each([
                ['team_id', { team_id: 'abc' }],
                ['team_id', { team_id: true }],
                ['team_id', { team_id: { a: 1 } }],
                ['offset', { offset: 'not-a-number' }],
                ['offset', { offset: [1] }],
            ])('%s with %j should DLQ', async (_field, dataOverrides) => {
                const result = await step({ message: makeMessage(dataOverrides) })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })
        })

        describe('object fields reject non-objects', () => {
            it.each([
                ['properties', { properties: 'string' }],
                ['properties', { properties: 123 }],
                ['properties', { properties: [1, 2] }],
                ['$set', { $set: 'string' }],
                ['$set', { $set: 42 }],
                ['$set_once', { $set_once: true }],
                ['$set_once', { $set_once: [1] }],
            ])('%s with %j should DLQ', async (_field, dataOverrides) => {
                const result = await step({ message: makeMessage(dataOverrides) })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })
        })

        describe('optional fields default correctly when absent', () => {
            it('should use defaults for all optional fields', async () => {
                const result = await step({ message: makeMessage() })

                expect(result.type).toBe(PipelineResultType.OK)
                const event = (result as any).value.event.event
                expect(event.ip).toBeNull()
                expect(event.site_url).toBe('')
                expect(event.now).toBe('')
                expect(event.team_id).toBeUndefined()
                expect(event.sent_at).toBeUndefined()
                expect(event.timestamp).toBeUndefined()
                expect(event.offset).toBeUndefined()
                expect(event.$set).toBeUndefined()
                expect(event.$set_once).toBeUndefined()
            })
        })

        describe('structural validation', () => {
            it.each([
                ['outer message is an array', JSON.stringify([1, 2, 3])],
                ['outer message is a string', JSON.stringify('hello')],
                ['outer message is a number', JSON.stringify(42)],
            ])('should DLQ when %s', async (_label, rawJson) => {
                const msg = { value: Buffer.from(rawJson) } as Message
                const result = await step({ message: msg })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })

            it.each([
                ['data field is an array', JSON.stringify([1, 2])],
                ['data field is a number', JSON.stringify(99)],
                ['data field is null', JSON.stringify(null)],
            ])('should DLQ when %s', async (_label, dataJson) => {
                const msg = {
                    value: Buffer.from(JSON.stringify({ data: dataJson, uuid: VALID_UUID })),
                } as Message
                const result = await step({ message: msg })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })

            it('should DLQ when data field is not a string', async () => {
                const msg = {
                    value: Buffer.from(JSON.stringify({ data: 123, uuid: VALID_UUID })),
                } as Message
                const result = await step({ message: msg })
                expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            })
        })
    })

    describe('edge cases', () => {
        it('should handle empty data field', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: '',
                        token: 'test_token',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should handle data field with only whitespace', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: '   ',
                        token: 'test_token',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should DLQ message with empty object in data and no uuid', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({}),
                        token: 'test_token',
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('empty_uuid'))
        })

        it('should DLQ message with null distinct_id', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: null,
                        }),
                        uuid: VALID_UUID,
                    })
                ),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
        })
    })
})
