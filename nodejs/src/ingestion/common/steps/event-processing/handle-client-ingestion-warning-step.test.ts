import { v4 } from 'uuid'

import { INGESTION_WARNINGS_OUTPUT, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { PipelineResultType } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'

import {
    HandleClientIngestionWarningStepInput,
    createHandleClientIngestionWarningStep,
} from './handle-client-ingestion-warning-step'

describe('handleClientIngestionWarningStep', () => {
    const eventUuid = v4()
    const capturedAt = new Date('2023-12-15T14:32:01.987Z')

    const baseEvent = createTestPluginEvent({
        distinct_id: 'my_id',
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event: '$pageview',
        properties: {},
        uuid: eventUuid,
    })

    let mockOutputs: jest.Mocked<IngestionOutputs<IngestionWarningsOutput>>
    let baseInput: HandleClientIngestionWarningStepInput

    beforeEach(() => {
        mockOutputs = createMockIngestionOutputs<IngestionWarningsOutput>()
        baseInput = {
            event: baseEvent,
            team: { id: 1 },
            headers: createTestEventHeaders({ now: capturedAt }),
            message: createTestMessage(),
        }
    })

    function producedWarning(): { team_id: number; type: string; details: Record<string, any> } {
        expect(mockOutputs.queueMessages).toHaveBeenCalledWith(INGESTION_WARNINGS_OUTPUT, [
            { value: expect.any(Buffer) },
        ])
        const value = mockOutputs.queueMessages.mock.calls[0][1][0].value
        if (value === null) {
            throw new Error('expected warning message to have a value')
        }
        const parsed = parseJSON(value.toString())
        return { ...parsed, details: parseJSON(parsed.details) }
    }

    describe('$$client_ingestion_warning events', () => {
        it('emits the warning and resolves ingested with the event info', async () => {
            const step = createHandleClientIngestionWarningStep(mockOutputs)
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: { $$client_ingestion_warning_message: 'Test warning message' },
                },
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.ingested).toHaveLength(1)
                expect(result.value.ingested).toEqual(result.sideEffects)
                await expect(result.value.ingested[0]).resolves.toEqual({
                    capturedAt,
                    topic: 'test-topic',
                    partition: 5,
                })
            }

            const warning = producedWarning()
            expect(warning.team_id).toBe(1)
            expect(warning.type).toBe('client_ingestion_warning')
            expect(warning.details).toMatchObject({
                eventUuid: eventUuid,
                event: '$$client_ingestion_warning',
                distinctId: 'my_id',
                message: 'Test warning message',
            })
        })

        it('handles missing warning message property', async () => {
            const step = createHandleClientIngestionWarningStep(mockOutputs)
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {},
                },
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(producedWarning().details.message).toBeUndefined()
        })

        it('resolves ingested with null when the warning could not be produced', async () => {
            mockOutputs.queueMessages.mockRejectedValue(new Error('produce failed'))
            const step = createHandleClientIngestionWarningStep(mockOutputs)
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$$client_ingestion_warning',
                    properties: {},
                },
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                await expect(result.value.ingested[0]).resolves.toBeNull()
            }
        })
    })

    describe('non-client ingestion warning events', () => {
        it.each([['$pageview'], ['$identify'], ['custom_event']])('DLQs %s events', async (eventName) => {
            const step = createHandleClientIngestionWarningStep(mockOutputs)
            const input: HandleClientIngestionWarningStepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: eventName,
                },
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.DLQ)
            if (result.type === PipelineResultType.DLQ) {
                expect(result.reason).toBe('unexpected_event_type')
                expect(result.error).toBeInstanceOf(Error)
                expect((result.error as Error).message).toBe(`Expected $$client_ingestion_warning, got ${eventName}`)
            }
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
        })
    })
})
