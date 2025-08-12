import { Message } from 'node-rdkafka'

import { parseKafkaMessage } from '../../../src/ingestion/event-preprocessing/parse-kafka-message'
import { logger } from '../../../src/utils/logger'

// Mock dependencies
jest.mock('../../../src/utils/logger')

describe('parseKafkaMessage', () => {
    const mockLogger = logger as jest.Mocked<typeof logger>

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('successful parsing', () => {
        it('should parse valid Kafka message with complete event data', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
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
            })
        })

        it('should parse message with minimal event data', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
                event: {
                    event: 'minimal_event',
                    distinct_id: 'user123',
                    ip: null,
                    properties: {},
                },
            })
        })

        it('should handle message with additional raw event fields', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
                event: {
                    event: 'test_event',
                    distinct_id: 'test_user',
                    custom_field: 'custom_value',
                    another_field: 42,
                    ip: null,
                    properties: {},
                },
            })
        })

        it('should preserve all properties from both data and raw event', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
                event: {
                    event: 'test_event',
                    distinct_id: 'test_user',
                    properties: { outer: 'value' }, // This will overwrite the inner properties
                    token: 'test_token',
                    ip: null,
                },
            })
        })

        it('should normalize event data during parsing', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
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
            })
        })
    })

    describe('error handling', () => {
        it('should return null when message value is null', () => {
            const mockMessage: Message = {
                value: null,
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when message value is undefined', () => {
            const mockMessage: Message = {
                value: undefined,
            } as unknown as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when outer JSON is invalid', () => {
            const mockMessage: Message = {
                value: Buffer.from('invalid json'),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when data field JSON is invalid', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: 'invalid json in data field',
                        token: 'test_token',
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when data field is missing', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        token: 'test_token',
                        // missing data field
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should return null when data field is not a string', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: { not: 'a string' },
                        token: 'test_token',
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })
    })

    describe('edge cases', () => {
        it('should handle empty data field', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: '',
                        token: 'test_token',
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should handle data field with only whitespace', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: '   ',
                        token: 'test_token',
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toBeNull()
            expect(mockLogger.warn).toHaveBeenCalledWith('Failed to parse Kafka message', {
                error: expect.any(Error),
            })
        })

        it('should handle message with empty object in data', () => {
            const mockMessage: Message = {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({}),
                        token: 'test_token',
                    })
                ),
            } as Message

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
                event: {
                    token: 'test_token',
                    distinct_id: 'undefined',
                    ip: null,
                    properties: {},
                },
            })
        })

        it('should handle message with null values', () => {
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

            const result = parseKafkaMessage(mockMessage)

            expect(result).toEqual({
                message: mockMessage,
                event: {
                    event: 'test_event',
                    distinct_id: 'null',
                    properties: {},
                    token: 'null',
                    ip: null,
                },
            })
        })
    })
})
