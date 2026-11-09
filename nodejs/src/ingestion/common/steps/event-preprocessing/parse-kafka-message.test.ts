import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { TopHogRegistry, createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { PipelineResultType, dlq, ok } from '~/ingestion/framework/results'
import { createRecordingTopHog } from '~/tests/helpers/tophog'
import { EventHeaders } from '~/types'

import { createParseKafkaMessageStep, parseMessageTopHogMetrics, v1OptionsAppliedTotal } from './parse-kafka-message'

// Mock dependencies
jest.mock('~/common/utils/logger')

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

    describe('capture v1 options', () => {
        const SPLICED: Message['headers'] = [{ legacy_property_splice: Buffer.from('true') }]

        beforeEach(() => {
            v1OptionsAppliedTotal.reset()
        })

        function makeMessage(
            data: Record<string, unknown>,
            outer: Record<string, unknown>,
            headers?: Message['headers']
        ): Message {
            return {
                value: Buffer.from(
                    JSON.stringify({
                        data: JSON.stringify({ event: 'test_event', distinct_id: 'test_user', ...data }),
                        uuid: VALID_UUID,
                        ...outer,
                    })
                ),
                headers,
            } as Message
        }

        async function parseMessage(message: Message): Promise<Record<string, unknown>> {
            const result = await step({ message })
            expect(result.type).toBe(PipelineResultType.OK)
            return (result as any).value.event.event.properties
        }

        function parseProperties(
            data: Record<string, unknown>,
            outer: Record<string, unknown>,
            headers?: Message['headers']
        ): Promise<Record<string, unknown>> {
            return parseMessage(makeMessage(data, outer, headers))
        }

        async function countedOutcomes(): Promise<Record<string, number>> {
            const { values } = await v1OptionsAppliedTotal.get()
            return Object.fromEntries(
                values.map(({ labels, value }) => [`${labels.key}:${labels.outcome}:${labels.splice}`, value])
            )
        }

        it.each([
            ['session_id', '$session_id', 'client-session', 'server-session'],
            ['window_id', '$window_id', 'client-window', 'server-window'],
            ['window_id', '$window_id', 'client-window', ''],
            ['cookieless_mode', '$cookieless_mode', false, true],
            ['disable_skew_correction', '$ignore_sent_at', true, false],
            ['product_tour_id', '$product_tour_id', 'client-tour', 'server-tour'],
            ['process_person_profile', '$process_person_profile', true, false],
        ])('%s overrides %s (client %j, server %j)', async (key, property, clientValue, serverValue) => {
            const properties = await parseProperties(
                { properties: { [property]: clientValue } },
                { options: { [key]: serverValue } }
            )

            expect(properties[property]).toBe(serverValue)
            expect(await countedOutcomes()).toEqual({ [`${key}:overridden:off`]: 1 })
        })

        it.each([
            ['missing', {}],
            ['null', { $session_id: null, $process_person_profile: null }],
        ])('fills a property that is %s', async (_label, clientProperties) => {
            const properties = await parseProperties(
                { properties: clientProperties },
                { options: { session_id: 'server-session', process_person_profile: false } }
            )

            expect(properties).toMatchObject({ $session_id: 'server-session', $process_person_profile: false })
            expect(await countedOutcomes()).toEqual({
                'session_id:filled:off': 1,
                'process_person_profile:filled:off': 1,
            })
        })

        it('counts an override that matches the client value as the same', async () => {
            const properties = await parseProperties(
                { properties: { $window_id: 'window', $process_person_profile: false } },
                { options: { window_id: 'window', process_person_profile: false } }
            )

            expect(properties).toMatchObject({ $window_id: 'window', $process_person_profile: false })
            expect(await countedOutcomes()).toEqual({
                'window_id:same:off': 1,
                'process_person_profile:same:off': 1,
            })
        })

        it.each([
            ['client sends none', {}],
            ['client sends the same value', { $session_id: '0191C5B8-6F3A-7A41-9D2E-1B2C3D4E5F60' }],
        ])('normalizes an uppercase UUID session id from options when the %s', async (_label, clientProperties) => {
            const properties = await parseProperties(
                { properties: clientProperties },
                { options: { session_id: '0191C5B8-6F3A-7A41-9D2E-1B2C3D4E5F60' } }
            )

            expect(properties.$session_id).toBe('0191c5b8-6f3a-7a41-9d2e-1b2c3d4e5f60')
        })

        it.each([
            ['missing', {}, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            ['null', { $lib: null, $lib_version: '0.9.0' }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            [
                'equal to the header',
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                'same',
            ],
            [
                'equal to the header without a version',
                { $lib: 'posthog-rs' },
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                'version_filled',
            ],
            [
                'equal to the header with a null version',
                { $lib: 'posthog-rs', $lib_version: null },
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                'version_filled',
            ],
            [
                'equal to the header with another version',
                { $lib: 'posthog-rs', $lib_version: '0.9.0' },
                { $lib: 'posthog-rs', $lib_version: '0.9.0' },
                'kept',
            ],
            [
                'set by the client',
                { $lib: 'posthog-rs-mcp', $lib_version: '0.3.0' },
                { $lib: 'posthog-rs-mcp', $lib_version: '0.3.0' },
                'kept',
            ],
            [
                'set by the client without a version',
                { $lib: 'custom' },
                { $lib: 'custom', $lib_version: undefined },
                'kept',
            ],
            [
                'set by the client with an empty version',
                { $lib: 'custom', $lib_version: '' },
                { $lib: 'custom', $lib_version: '' },
                'kept',
            ],
            [
                'equal to the header with an empty version',
                { $lib: 'posthog-rs', $lib_version: '' },
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                'version_filled',
            ],
            [
                'equal to the header with a non-string version',
                { $lib: 'posthog-rs', $lib_version: 1 },
                { $lib: 'posthog-rs', $lib_version: '1.0.0' },
                'version_filled',
            ],
            [
                'equal to the header with a whitespace version',
                { $lib: 'posthog-rs', $lib_version: ' ' },
                { $lib: 'posthog-rs', $lib_version: ' ' },
                'kept',
            ],
            ['whitespace', { $lib: ' ' }, { $lib: ' ', $lib_version: undefined }, 'kept'],
            ['an empty string', { $lib: '' }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            ['an array', { $lib: ['posthog-rs'] }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            ['a number', { $lib: 5 }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            ['a boolean', { $lib: true }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
            ['an object', { $lib: {} }, { $lib: 'posthog-rs', $lib_version: '1.0.0' }, 'filled'],
        ])('handles $lib that is %s', async (_label, clientProperties, expected, outcome) => {
            const properties = await parseProperties(
                { properties: clientProperties },
                { options: { req_lib: 'posthog-rs', req_lib_version: '1.0.0' } }
            )

            expect({ $lib: properties.$lib, $lib_version: properties.$lib_version }).toEqual(expected)
            expect(await countedOutcomes()).toEqual({ [`req_lib:${outcome}:off`]: 1 })
        })

        it.each([
            ['a string option is a number', { session_id: 42 }, 'session_id'],
            ['a bool option is a string', { cookieless_mode: 'true' }, 'cookieless_mode'],
            ['an option is null', { window_id: null }, 'window_id'],
            ['req_lib_version is missing', { req_lib: 'posthog-rs' }, 'req_lib'],
            ['req_lib is missing', { req_lib_version: '1.0.0' }, 'req_lib'],
            ['req_lib is not a string', { req_lib: 1, req_lib_version: '1.0.0' }, 'req_lib'],
        ])('skips the value when %s', async (_label, options, key) => {
            const clientProperties = { $session_id: 'client', $cookieless_mode: false, $window_id: 'client' }

            const properties = await parseProperties({ properties: clientProperties }, { options })

            expect(properties).toMatchObject(clientProperties)
            expect(properties.$lib).toBeUndefined()
            expect(await countedOutcomes()).toEqual({ [`${key}:invalid_type:off`]: 1 })
        })

        it.each([
            ['req_lib is empty', { req_lib: '', req_lib_version: '1.0.0' }],
            ['req_lib is whitespace', { req_lib: ' ', req_lib_version: '1.0.0' }],
            ['req_lib_version is empty', { req_lib: 'posthog-rs', req_lib_version: '' }],
            ['req_lib_version is whitespace', { req_lib: 'posthog-rs', req_lib_version: '\t' }],
        ])('treats the header pair as missing when %s', async (_label, options) => {
            const properties = await parseProperties({ properties: { $lib_version: '0.9.0' } }, { options })

            expect({ $lib: properties.$lib, $lib_version: properties.$lib_version }).toEqual({
                $lib: undefined,
                $lib_version: '0.9.0',
            })
            expect(await countedOutcomes()).toEqual({ 'req_lib:empty:off': 1 })
        })

        it.each([
            ['a string', 'session_id'],
            ['an array', ['session_id']],
            ['null', null],
        ])('ignores options that are %s', async (_label, options) => {
            const properties = await parseProperties({ properties: { $session_id: 'client' } }, { options })

            expect(properties.$session_id).toBe('client')
            expect(await countedOutcomes()).toEqual({ 'options:invalid_type:off': 1 })
        })

        it('ignores options inside the client-controlled data field', async () => {
            const properties = await parseProperties(
                {
                    properties: { $session_id: 'client' },
                    options: { session_id: 'injected', req_lib: 'injected', req_lib_version: '1.0.0' },
                },
                {}
            )

            expect(properties.$session_id).toBe('client')
            expect(properties.$lib).toBeUndefined()
            expect(await countedOutcomes()).toEqual({})
        })

        it('applies options to an event without properties', async () => {
            const properties = await parseProperties(
                {},
                { options: { process_person_profile: false, req_lib: 'posthog-go', req_lib_version: '2.0.0' } }
            )

            expect(properties).toEqual({
                $process_person_profile: false,
                $lib: 'posthog-go',
                $lib_version: '2.0.0',
            })
        })

        it('leaves unknown option keys out of the event', async () => {
            const properties = await parseProperties({ properties: { a: 1 } }, { options: { future_key: 'x' } })

            expect(properties).toEqual({ a: 1 })
            expect(await countedOutcomes()).toEqual({})
        })

        it('does not count events without options, even with the splice header', async () => {
            await parseProperties({ properties: { $session_id: 'client' } }, {}, SPLICED)

            expect(await countedOutcomes()).toEqual({})
        })

        it('labels outcomes from spliced messages with splice on', async () => {
            await parseProperties(
                { properties: { $session_id: 'server-session' } },
                { options: { session_id: 'server-session', window_id: 'server-window' } },
                SPLICED
            )

            expect(await countedOutcomes()).toEqual({
                'session_id:same:on': 1,
                'window_id:filled:on': 1,
            })
        })

        it('reads capture spliced bytes, with duplicate keys, as all same', async () => {
            const data =
                '{"event":"test_event","distinct_id":"test_user","properties":{"$lib":"client-lib","$session_id":"client-session",' +
                '"$session_id":"server-session","$process_person_profile":false,"$lib":"posthog-rs","$lib_version":"1.0.0"}}'
            const options = {
                session_id: 'server-session',
                process_person_profile: false,
                req_lib: 'posthog-rs',
                req_lib_version: '1.0.0',
            }
            const message = {
                value: Buffer.from(JSON.stringify({ data, uuid: VALID_UUID, options })),
                headers: SPLICED,
            } as Message

            const properties = await parseMessage(message)

            expect(properties).toMatchObject({
                $session_id: 'server-session',
                $process_person_profile: false,
                $lib: 'posthog-rs',
                $lib_version: '1.0.0',
            })
            expect(await countedOutcomes()).toEqual({
                'session_id:same:on': 1,
                'process_person_profile:same:on': 1,
                'req_lib:same:on': 1,
            })
        })
    })

    describe('parseMessageTopHogMetrics', () => {
        function createWrappedStep(registry: TopHogRegistry) {
            return createTopHogWrapper(registry)(
                createParseKafkaMessageStep<{ message: Message; headers: EventHeaders }>(),
                parseMessageTopHogMetrics()
            )
        }

        const baseHeaders = {
            force_disable_person_processing: false,
            historical_migration: false,
            skip_heatmap_processing: false,
        }

        it('records sizes and timing keyed by token, including for messages that fail to parse', async () => {
            const { registry, records } = createRecordingTopHog()
            const wrapped = createWrappedStep(registry)

            const malformed = Buffer.from('not json')
            const result = await wrapped({
                message: { value: malformed, partition: 7 } as Message,
                headers: { ...baseHeaders, token: 'token-a' },
            })

            // The parse itself DLQ'd — the metrics below were still recorded
            // from the raw message.
            expect(result).toEqual(dlq('failed_parse_message', expect.any(Error)))
            expect(records.get('messages_by_token')).toEqual([{ key: { token: 'token-a' }, value: 1 }])
            expect(records.get('message_size_by_token')).toEqual([
                { key: { token: 'token-a' }, value: malformed.length },
            ])
            expect(records.get('max_message_size_by_token')).toEqual([
                { key: { token: 'token-a' }, value: malformed.length },
            ])
            expect(records.get('message_size_by_token_per_partition')).toEqual([
                { key: { token: 'token-a', partition: '7' }, value: malformed.length },
            ])
            const timings = records.get('parse_time_ms_by_token')!
            expect(timings).toHaveLength(1)
            expect(timings[0].key).toEqual({ token: 'token-a' })
            expect(timings[0].value).toBeGreaterThanOrEqual(0)
            expect([...records.keys()].sort()).toEqual([
                'max_message_size_by_token',
                'message_size_by_token',
                'message_size_by_token_per_partition',
                'messages_by_token',
                'parse_time_ms_by_token',
            ])
        })

        it('records a successful parse the same way, falling back to an unknown token key', async () => {
            const { registry, records } = createRecordingTopHog()
            const wrapped = createWrappedStep(registry)

            const value = Buffer.from(
                JSON.stringify({
                    data: JSON.stringify({ event: 'test_event', distinct_id: 'user' }),
                    uuid: VALID_UUID,
                })
            )
            const result = await wrapped({
                message: { value, partition: 0 } as Message,
                headers: baseHeaders,
            })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(records.get('messages_by_token')).toEqual([{ key: { token: 'unknown' }, value: 1 }])
            expect(records.get('message_size_by_token')).toEqual([{ key: { token: 'unknown' }, value: value.length }])
            expect(records.get('max_message_size_by_token')).toEqual([
                { key: { token: 'unknown' }, value: value.length },
            ])
            expect(records.get('message_size_by_token_per_partition')).toEqual([
                { key: { token: 'unknown', partition: '0' }, value: value.length },
            ])
            expect(records.get('parse_time_ms_by_token')![0].key).toEqual({ token: 'unknown' })
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
