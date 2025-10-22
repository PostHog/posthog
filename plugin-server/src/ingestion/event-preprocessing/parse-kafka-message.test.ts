import { Message } from 'node-rdkafka'

import { logger } from '../../utils/logger'
import { drop, ok } from '../pipelines/results'
import { createParseKafkaMessageStep } from './parse-kafka-message'

// Mock dependencies
jest.mock('../../../src/utils/logger')

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
                        uuid: 'test-uuid',
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
                            token: 'test_token',
                            ip: null,
                            site_url: 'https://example.com',
                            uuid: 'test-uuid',
                            now: '2023-01-01T00:00:00Z',
                            sent_at: '2023-01-01T00:00:01Z',
                            kafka_offset: '123',
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
                            ip: null,
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
                            custom_field: 'custom_value',
                            another_field: 42,
                            ip: null,
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
                            properties: { outer: 'value' }, // This will overwrite the inner properties
                            token: 'test_token',
                            ip: null,
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
                            token: 'test\uFFFDtoken', // null byte replaced with replacement character
                            ip: null, // ip field set to null for safety
                            sent_at: '2023-01-01T00:00:01Z',
                        },
                    },
                })
            )
        })
    })

    describe('error handling', () => {
        it('should return null when message value is null', async () => {
            const mockMessage: Message = {
                value: null,
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(drop('failed_parse_message'))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when message value is undefined', async () => {
            const mockMessage: Message = {
                value: undefined,
            } as unknown as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(drop('failed_parse_message'))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when outer JSON is invalid', async () => {
            const mockMessage: Message = {
                value: Buffer.from('invalid json'),
            } as Message

            const input = { message: mockMessage }
            const result = await step(input)

            expect(result).toEqual(drop('failed_parse_message'))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when data field JSON is invalid', async () => {
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

            expect(result).toEqual(drop('failed_parse_message'))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
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

            expect(result).toEqual(drop('failed_parse_message'))
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

            expect(result).toEqual(drop('failed_parse_message'))
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should handle message with empty object in data', async () => {
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

            expect(result).toEqual(
                ok({
                    message: mockMessage,
                    event: {
                        event: {
                            token: 'test_token',
                            distinct_id: 'undefined',
                            ip: null,
                            properties: {},
                        },
                    },
                })
            )
        })

        it('should handle message with null values', async () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({
                            event: 'test_event',
                            distinct_id: null,
                            properties: null,
                        }),
                        token: null,
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
                            distinct_id: 'null',
                            properties: {},
                            token: 'null',
                            ip: null,
                        },
                    },
                })
            )
        })
    })
})
