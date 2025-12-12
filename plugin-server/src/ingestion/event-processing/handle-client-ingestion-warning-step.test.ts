import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { PipelineEvent, ProjectId, Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { EventPipelineRunnerInput } from './event-pipeline-runner-v1-step'
import { createHandleClientIngestionWarningStep } from './handle-client-ingestion-warning-step'

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    ...overrides,
})

describe('handleClientIngestionWarningStep', () => {
    const team = createTestTeam()
    const eventUuid = v4()

    const baseEvent: PipelineEvent = {
        distinct_id: 'my_id',
        ip: null,
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event: '$pageview',
        properties: {},
        uuid: eventUuid,
    }

    const baseInput: EventPipelineRunnerInput = {
        message: {} as Message,
        event: baseEvent,
        team,
        headers: createTestEventHeaders(),
        groupStoreForBatch: {} as any,
        processPerson: true,
        forceDisablePersonProcessing: false,
    }

    const handleStep = createHandleClientIngestionWarningStep()

    describe('$$client_ingestion_warning events', () => {
        it('processes $$client_ingestion_warning event and adds warning', async () => {
            const input: EventPipelineRunnerInput = {
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
            const input: EventPipelineRunnerInput = {
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
            const input: EventPipelineRunnerInput = {
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
    })

    describe('non-client ingestion warning events', () => {
        it('DLQs regular events', async () => {
            const input: EventPipelineRunnerInput = {
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
            const input: EventPipelineRunnerInput = {
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
            const input: EventPipelineRunnerInput = {
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
