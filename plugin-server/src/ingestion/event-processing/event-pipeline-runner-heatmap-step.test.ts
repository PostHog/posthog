import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, PipelineEvent, ProjectId, RawKafkaEvent, Team, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { EventPipelineHeatmapResult, EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResultType, dlq, drop, ok } from '../pipelines/results'
import { createEventPipelineRunnerHeatmapStep } from './event-pipeline-runner-heatmap-step'

jest.mock('../../worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn(),
}))

jest.mock('../../utils/retries', () => ({
    retryIfRetriable: jest.fn((fn) => fn()),
}))

jest.mock('../../utils/logger', () => ({
    logger: {
        error: jest.fn(),
    },
}))

jest.mock('../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

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

const createTestRawKafkaEvent = (overrides: Partial<RawKafkaEvent> = {}): RawKafkaEvent => {
    const testTimestamp = castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ClickHouse)
    return {
        uuid: 'test-uuid',
        event: '$$heatmap',
        properties: JSON.stringify({ test: 'property' }),
        timestamp: testTimestamp,
        team_id: 1,
        project_id: 1 as ProjectId,
        distinct_id: 'test-distinct-id',
        elements_chain: '',
        created_at: testTimestamp,
        person_id: 'person-uuid',
        person_properties: JSON.stringify({}),
        person_created_at: testTimestamp,
        person_mode: 'full',
        ...overrides,
    }
}

describe('event-pipeline-runner-heatmap-step', () => {
    let mockHub: Hub
    let mockHogTransformer: HogTransformerService
    let mockPersonsStore: PersonsStore
    let mockGroupStore: GroupStoreForBatch
    let mockEventPipelineRunner: jest.Mocked<EventPipelineRunner>
    let mockEvent: PipelineEvent
    let mockTeam: Team
    let mockHeaders: EventHeaders

    beforeEach(() => {
        jest.clearAllMocks()

        mockHub = {} as Hub
        mockHogTransformer = {} as HogTransformerService
        mockPersonsStore = {} as PersonsStore
        mockGroupStore = {} as GroupStoreForBatch

        mockEvent = {
            uuid: v4(),
            distinct_id: 'test-distinct-id',
            ip: null,
            site_url: '',
            team_id: 1,
            now: new Date().toISOString(),
            event: '$$heatmap',
            properties: { $elements: [{ tag_name: 'div' }] },
        }

        mockTeam = createTestTeam()
        mockHeaders = createTestEventHeaders()

        mockEventPipelineRunner = {
            runHeatmapPipeline: jest.fn(),
        } as any
        ;(EventPipelineRunner as jest.Mock).mockImplementation(() => mockEventPipelineRunner)
    })

    it('should create EventPipelineRunner and call runHeatmapPipeline', async () => {
        const mockTimestamp = DateTime.now()
        const mockRawEvent = createTestRawKafkaEvent()
        const mockResult = ok({ lastStep: 'extractHeatmapDataStep', eventToEmit: mockRawEvent })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer, mockPersonsStore)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        const result = await step(input)

        expect(EventPipelineRunner).toHaveBeenCalledWith(
            mockHub,
            mockEvent,
            mockHogTransformer,
            mockPersonsStore,
            mockGroupStore,
            mockHeaders
        )
        expect(mockEventPipelineRunner.runHeatmapPipeline).toHaveBeenCalledWith(mockEvent, mockTimestamp, mockTeam)
        // Result is transformed to EmitEventStepInput
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toEqual({ eventToEmit: mockRawEvent, lastStep: 'extractHeatmapDataStep' })
        }
    })

    it('should pass through drop results from runHeatmapPipeline', async () => {
        const mockTimestamp = DateTime.now()
        const mockResult = drop<EventPipelineHeatmapResult>('heatmap_processing_failed')
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer, mockPersonsStore)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        const result = await step(input)

        expect(result).toEqual(mockResult)
        expect(result.type).toBe(PipelineResultType.DROP)
    })

    it('should pass through DLQ results from runHeatmapPipeline', async () => {
        const mockTimestamp = DateTime.now()
        const mockError = new Error('Heatmap processing error')
        const mockResult = dlq<EventPipelineHeatmapResult>('heatmap_error', mockError)
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer, mockPersonsStore)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        const result = await step(input)

        expect(result).toEqual(mockResult)
        expect(result.type).toBe(PipelineResultType.DLQ)
    })

    it('should use the correct headers when processing', async () => {
        const mockTimestamp = DateTime.now()
        const customHeaders = createTestEventHeaders({ force_disable_person_processing: true })

        const mockResult = ok({ lastStep: 'extractHeatmapDataStep', eventToEmit: createTestRawKafkaEvent() })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer, mockPersonsStore)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: customHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        await step(input)

        expect(EventPipelineRunner).toHaveBeenCalledWith(
            mockHub,
            mockEvent,
            mockHogTransformer,
            mockPersonsStore,
            mockGroupStore,
            customHeaders
        )
    })
})
