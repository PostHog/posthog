import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, ISOTimestamp, PipelineEvent, PreIngestionEvent, ProjectId, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import {
    EventPipelineHeatmapResult,
    EventPipelineRunner,
    EventPipelineRunnerOptions,
} from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
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

const createTestPreIngestionEvent = (overrides: Partial<PreIngestionEvent> = {}): PreIngestionEvent => {
    return {
        eventUuid: 'test-uuid',
        event: '$$heatmap',
        teamId: 1,
        projectId: 1 as ProjectId,
        distinctId: 'test-distinct-id',
        properties: { test: 'property' },
        timestamp: '2023-01-01T00:00:00.000Z' as ISOTimestamp,
        ...overrides,
    }
}

describe('event-pipeline-runner-heatmap-step', () => {
    let mockConfig: EventPipelineRunnerOptions
    let mockKafkaProducer: KafkaProducerWrapper
    let mockTeamManager: TeamManager
    let mockGroupTypeManager: GroupTypeManager
    let mockHogTransformer: HogTransformerService
    let mockPersonsStore: PersonsStore
    let mockGroupStore: GroupStoreForBatch
    let mockEventPipelineRunner: jest.Mocked<EventPipelineRunner>
    let mockEvent: PipelineEvent
    let mockTeam: Team
    let mockHeaders: EventHeaders

    beforeEach(() => {
        jest.clearAllMocks()

        mockConfig = {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
            TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: 0,
            PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30000,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
            PERSON_MERGE_ASYNC_ENABLED: false,
            PERSON_MERGE_ASYNC_TOPIC: '',
            PERSON_MERGE_SYNC_BATCH_SIZE: 1,
            PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
            PERSON_PROPERTIES_UPDATE_ALL: false,
        }
        mockKafkaProducer = {} as KafkaProducerWrapper
        mockTeamManager = {} as TeamManager
        mockGroupTypeManager = {} as GroupTypeManager
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
        const mockResult = ok({ lastStep: 'prepareEventStep', preparedEvent: createTestPreIngestionEvent() })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockHogTransformer,
            mockPersonsStore
        )

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        const result = await step(input)

        expect(EventPipelineRunner).toHaveBeenCalledWith(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockEvent,
            mockHogTransformer,
            mockPersonsStore,
            mockGroupStore,
            mockHeaders
        )
        expect(mockEventPipelineRunner.runHeatmapPipeline).toHaveBeenCalledWith(mockEvent, mockTimestamp, mockTeam)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent).toEqual(createTestPreIngestionEvent())
            expect(result.value).toMatchObject(input)
        }
    })

    it('should pass through drop results from runHeatmapPipeline', async () => {
        const mockTimestamp = DateTime.now()
        const mockResult = drop<EventPipelineHeatmapResult>('heatmap_processing_failed')
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockHogTransformer,
            mockPersonsStore
        )

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

        const step = createEventPipelineRunnerHeatmapStep(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockHogTransformer,
            mockPersonsStore
        )

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

        const mockResult = ok({ lastStep: 'prepareEventStep', preparedEvent: createTestPreIngestionEvent() })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockHogTransformer,
            mockPersonsStore
        )

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: customHeaders,
            groupStoreForBatch: mockGroupStore,
        }

        await step(input)

        expect(EventPipelineRunner).toHaveBeenCalledWith(
            mockConfig,
            mockKafkaProducer,
            mockTeamManager,
            mockGroupTypeManager,
            mockEvent,
            mockHogTransformer,
            mockPersonsStore,
            mockGroupStore,
            customHeaders
        )
    })
})
