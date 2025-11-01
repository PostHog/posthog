import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub, ISOTimestamp, PipelineEvent, PreIngestionEvent, ProjectId, Team } from '../../types'
import { EventPipelineHeatmapResult, EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
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
    let mockHub: Hub
    let mockHogTransformer: HogTransformerService
    let mockPersonsStore: PersonsStoreForBatch
    let mockGroupStore: GroupStoreForBatch
    let mockEventPipelineRunner: jest.Mocked<EventPipelineRunner>
    let mockEvent: PipelineEvent
    let mockTeam: Team
    let mockHeaders: any

    beforeEach(() => {
        jest.clearAllMocks()

        mockHub = {} as Hub
        mockHogTransformer = {} as HogTransformerService
        mockPersonsStore = {} as PersonsStoreForBatch
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
        mockHeaders = { force_disable_person_processing: false }

        mockEventPipelineRunner = {
            runHeatmapPipeline: jest.fn(),
        } as any
        ;(EventPipelineRunner as jest.Mock).mockImplementation(() => mockEventPipelineRunner)
    })

    it('should create EventPipelineRunner and call runHeatmapPipeline', async () => {
        const mockTimestamp = DateTime.now()
        const mockResult = ok({ lastStep: 'prepareEventStep', preparedEvent: createTestPreIngestionEvent() })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            personsStoreForBatch: mockPersonsStore,
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

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            personsStoreForBatch: mockPersonsStore,
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

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: mockHeaders,
            personsStoreForBatch: mockPersonsStore,
            groupStoreForBatch: mockGroupStore,
        }

        const result = await step(input)

        expect(result).toEqual(mockResult)
        expect(result.type).toBe(PipelineResultType.DLQ)
    })

    it('should use the correct headers when processing', async () => {
        const mockTimestamp = DateTime.now()
        const customHeaders = {
            force_disable_person_processing: true,
            custom_header: 'value',
        }

        const mockResult = ok({ lastStep: 'prepareEventStep', preparedEvent: createTestPreIngestionEvent() })
        mockEventPipelineRunner.runHeatmapPipeline.mockResolvedValue(mockResult)

        const step = createEventPipelineRunnerHeatmapStep(mockHub, mockHogTransformer)

        const input = {
            normalizedEvent: mockEvent,
            timestamp: mockTimestamp,
            team: mockTeam,
            headers: customHeaders,
            personsStoreForBatch: mockPersonsStore,
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
