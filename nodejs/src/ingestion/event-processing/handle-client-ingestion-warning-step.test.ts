import { v4 } from 'uuid'

import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { PipelineResultType } from '../pipelines/results'
import {
    HandleClientIngestionWarningStepInput,
    createHandleClientIngestionWarningStep,
} from './handle-client-ingestion-warning-step'

describe('handleClientIngestionWarningStep', () => {
    const eventUuid = v4()

    const baseEvent = createTestPluginEvent({
        distinct_id: 'my_id',
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event: '$pageview',
        properties: {},
        uuid: eventUuid,
    })

    const baseInput: HandleClientIngestionWarningStepInput = {
        event: baseEvent,
    }

    const handleStep = createHandleClientIngestionWarningStep()

    describe('$$client_ingestion_warning events', () => {
        it('processes $$client_ingestion_warning event and adds warning', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: { $$client_ingestion_warning_message: 'Test warning message' },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value).toBeUndefined()
            }
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({
                type: 'client_ingestion_warning',
                details: {
                    eventUuid: eventUuid,
                    event: '$$client_ingestion_warning',
                    distinctId: 'my_id',
                    message: 'Test warning message',
                },
                alwaysSend: true,
            })
        })

        it('includes message property in warning details', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: { $$client_ingestion_warning_message: 'Custom error message!' },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value).toBeUndefined()
            }
            expect(result.warnings[0].details.message).toBe('Custom error message!')
        })

        it('handles missing warning message property', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {},
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value).toBeUndefined()
            }
            expect(result.warnings[0].details.message).toBeUndefined()
        })

        it('caps an oversized client message and drops non-string messages', async () => {
            const oversized = await handleStep({
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: { $$client_ingestion_warning_message: 'x'.repeat(100000) },
                },
            })
            expect(oversized.warnings[0].details.message).toBeUndefined()

            const nonString = await handleStep({
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: { $$client_ingestion_warning_message: { nested: 'x'.repeat(100000) } },
                },
            })
            expect(nonString.warnings[0].details.message).toBeUndefined()
        })

        it.each(['constructor', '__proto__', 'hasOwnProperty', 'toString', 'valueOf'])(
            'does not let the forged prototype-key type %s bypass the allowlist',
            async (forgedType) => {
                const input: HandleClientIngestionWarningStepInput = {
                    ...baseInput,
                    event: {
                        ...baseEvent,
                        event: '$$client_ingestion_warning',
                        properties: {
                            $$client_ingestion_warning_type: forgedType,
                            $$client_ingestion_warning_details: {
                                replayRecord: { session_id: 'session-abc' },
                                timestamp: '2026-06-12T10:00:00.000Z',
                                injected: 'x'.repeat(100000),
                            },
                        },
                    },
                }

                // a prototype-chain lookup would either throw or persist the raw payload
                const result = await handleStep(input)

                expect(result.type).toBe(PipelineResultType.OK)
                expect(result.warnings[0].type).toBe('client_ingestion_warning')
                expect(result.warnings[0].details.injected).toBeUndefined()
                expect(result.warnings[0].key).toBeUndefined()
                expect(result.warnings[0].alwaysSend).toBe(true)
            }
        )
    })

    describe('warning type overrides', () => {
        const replayDetails = {
            timestamp: '2026-06-12T10:00:00.000Z',
            replayRecord: { session_id: 'session-abc' },
            snapshotBytes: 21000000,
            snapshotItemsCount: 3,
        }

        it('honors the replay_message_too_large override with valid details', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_message: 'Replay data dropped',
                        $$client_ingestion_warning_type: 'replay_message_too_large',
                        $$client_ingestion_warning_details: replayDetails,
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({
                type: 'replay_message_too_large',
                details: {
                    ...replayDetails,
                    eventUuid: eventUuid,
                    distinctId: 'my_id',
                    message: 'Replay data dropped',
                },
                key: 'session-abc',
            })
            expect(result.warnings[0].alwaysSend).toBeUndefined()
        })

        it('persists only the sanitized fields, never the raw client payload', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_type: 'replay_message_too_large',
                        $$client_ingestion_warning_details: {
                            ...replayDetails,
                            replayRecord: { session_id: 'session-abc', injected: 'x'.repeat(100000) },
                            snapshotBytes: 'not-a-number',
                            arbitraryBlob: { nested: 'x'.repeat(100000) },
                        },
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe('replay_message_too_large')
            expect(result.warnings[0].details.arbitraryBlob).toBeUndefined()
            expect(result.warnings[0].details.snapshotBytes).toBeUndefined()
            expect(result.warnings[0].details.replayRecord).toEqual({ session_id: 'session-abc' })
        })

        it('does not persist client details on the generic fallback', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_message: 'some message',
                        $$client_ingestion_warning_details: { arbitraryBlob: 'x'.repeat(100000) },
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0]).toMatchObject({ type: 'client_ingestion_warning', alwaysSend: true })
            expect(result.warnings[0].details.arbitraryBlob).toBeUndefined()
        })

        it.each([
            ['missing details', undefined],
            ['details without replayRecord', { timestamp: '2026-06-12T10:00:00.000Z' }],
            ['replayRecord without session_id', { timestamp: '2026-06-12T10:00:00.000Z', replayRecord: {} }],
            ['missing timestamp', { replayRecord: { session_id: 'session-abc' } }],
            ['non-string timestamp', { timestamp: 123, replayRecord: { session_id: 'session-abc' } }],
            ['oversized timestamp', { timestamp: 'x'.repeat(1000), replayRecord: { session_id: 'session-abc' } }],
            [
                'non-string session_id',
                { timestamp: '2026-06-12T10:00:00.000Z', replayRecord: { session_id: { evil: true } } },
            ],
            [
                'oversized session_id',
                { timestamp: '2026-06-12T10:00:00.000Z', replayRecord: { session_id: 'x'.repeat(1000) } },
            ],
            ['non-object details', 'not-an-object'],
        ])('falls back to client_ingestion_warning when override has %s', async (_name, details) => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_type: 'replay_message_too_large',
                        $$client_ingestion_warning_details: details,
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe('client_ingestion_warning')
        })

        it.each([
            ['valid reason', { reason: 'invalid_session_id', sessionId: 'bad!id' }, 'replay_message_invalid'],
            ['missing reason', { sessionId: 'bad!id' }, 'client_ingestion_warning'],
            ['non-string reason', { reason: 42 }, 'client_ingestion_warning'],
            ['oversized reason', { reason: 'x'.repeat(1000) }, 'client_ingestion_warning'],
        ])('replay_message_invalid override with %s', async (_name, details, expectedType) => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_type: 'replay_message_invalid',
                        $$client_ingestion_warning_details: details,
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe(expectedType)
        })

        it.each([
            [
                'debounces per session when a session id is present',
                { reason: 'invalid_session_id', sessionId: 'bad!id' },
                'bad!id',
                { reason: 'invalid_session_id', sessionId: 'bad!id' },
            ],
            [
                'debounces per reason when the session id is missing',
                { reason: 'missing_session_id' },
                'missing_session_id',
                { reason: 'missing_session_id', sessionId: undefined },
            ],
            [
                'drops non-string session ids and extra client fields',
                { reason: 'missing_snapshot_data', sessionId: { evil: true }, arbitraryBlob: 'x'.repeat(100000) },
                'missing_snapshot_data',
                { reason: 'missing_snapshot_data', sessionId: undefined },
            ],
        ])('replay_message_invalid %s', async (_name, details, expectedKey, expectedDetails) => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_type: 'replay_message_invalid',
                        $$client_ingestion_warning_details: details,
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe('replay_message_invalid')
            expect(result.warnings[0].key).toBe(expectedKey)
            expect(result.warnings[0].alwaysSend).toBeUndefined()
            expect(result.warnings[0].details).toMatchObject(expectedDetails)
            expect(result.warnings[0].details.arbitraryBlob).toBeUndefined()
        })

        it('ignores warning types outside the allowlist', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_type: 'cannot_merge_already_identified',
                        $$client_ingestion_warning_details: replayDetails,
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe('client_ingestion_warning')
        })

        it('does not let extra details override the base detail fields', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {
                        $$client_ingestion_warning_message: 'real message',
                        $$client_ingestion_warning_type: 'replay_message_too_large',
                        $$client_ingestion_warning_details: {
                            ...replayDetails,
                            eventUuid: 'spoofed',
                            message: 'spoofed',
                        },
                    },
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings[0].type).toBe('replay_message_too_large')
            expect(result.warnings[0].details.eventUuid).toBe(eventUuid)
            expect(result.warnings[0].details.message).toBe('real message')
        })
    })

    describe('non-client ingestion warning events', () => {
        it('DLQs regular events', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$pageview',
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.DLQ)
            if (result.type === PipelineResultType.DLQ) {
                expect(result.reason).toBe('unexpected_event_type')
                expect(result.error).toBeInstanceOf(Error)
                expect((result.error as Error).message).toBe('Expected $$client_ingestion_warning, got $pageview')
            }
        })

        it('DLQs $identify events', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$identify',
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.DLQ)
            if (result.type === PipelineResultType.DLQ) {
                expect(result.reason).toBe('unexpected_event_type')
                expect(result.error).toBeInstanceOf(Error)
                expect((result.error as Error).message).toBe('Expected $$client_ingestion_warning, got $identify')
            }
        })

        it('DLQs custom events', async () => {
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: 'custom_event',
                },
            }

            const result = await handleStep(input)

            expect(result.type).toBe(PipelineResultType.DLQ)
            if (result.type === PipelineResultType.DLQ) {
                expect(result.reason).toBe('unexpected_event_type')
                expect(result.error).toBeInstanceOf(Error)
                expect((result.error as Error).message).toBe('Expected $$client_ingestion_warning, got custom_event')
            }
        })
    })
})
