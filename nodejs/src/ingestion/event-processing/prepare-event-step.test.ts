import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { createTestPerson } from '../../../tests/helpers/person'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { EventHeaders, Person, PreIngestionEvent, ProjectId, Team, TimestampFormat } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { EventsProcessor } from '../../worker/ingestion/process-event'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { processAiEvent } from '../ai'
import { PipelineResultType } from '../pipelines/results'
import { createPrepareEventStep } from './prepare-event-step'

jest.mock('../../worker/ingestion/process-event')
jest.mock('../../worker/ingestion/timestamps')
jest.mock('../ai')

const createTestPreIngestionEvent = (overrides: Partial<PreIngestionEvent> = {}): PreIngestionEvent => ({
    eventUuid: 'test-uuid',
    event: 'test-event',
    teamId: 1,
    projectId: 1 as ProjectId,
    distinctId: 'test-distinct-id',
    properties: {},
    timestamp: castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ISO),
    ...overrides,
})

type TestInput = {
    normalizedEvent: PluginEvent
    team: Team
    processPerson: boolean
    person: Person
    headers: EventHeaders
    message: Message
}

describe('createPrepareEventStep', () => {
    let mockTeamManager: TeamManager
    let mockGroupTypeManager: GroupTypeManager
    let mockGroupStore: BatchWritingGroupStore
    let mockEvent: PluginEvent
    let mockPerson: Person
    let mockTeam: Team
    let mockHeaders: EventHeaders
    let mockMessage: Message
    let mockProcessEvent: jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()

        mockTeamManager = {} as TeamManager
        mockGroupTypeManager = {} as GroupTypeManager
        mockGroupStore = {} as BatchWritingGroupStore

        mockEvent = createTestPluginEvent()
        mockPerson = createTestPerson()
        mockTeam = createTestTeam()
        mockHeaders = createTestEventHeaders()
        mockMessage = createTestMessage()

        mockProcessEvent = jest.fn()
        jest.mocked(EventsProcessor).mockImplementation(
            () => ({ processEvent: mockProcessEvent }) as unknown as EventsProcessor
        )
        jest.mocked(parseEventTimestamp).mockReturnValue(DateTime.fromISO('2023-01-01T00:00:00.000Z'))
    })

    const createInput = (overrides: Partial<TestInput> = {}): TestInput => ({
        normalizedEvent: mockEvent,
        team: mockTeam,
        processPerson: true,
        person: mockPerson,
        headers: mockHeaders,
        message: mockMessage,
        ...overrides,
    })

    it.each([
        { desc: 'with processPerson=true', processPerson: true },
        { desc: 'with processPerson=false', processPerson: false },
    ])('should process event and return prepared result $desc', async ({ processPerson }) => {
        const preparedEvent = createTestPreIngestionEvent()
        mockProcessEvent.mockResolvedValue(preparedEvent)

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        const input = createInput({ processPerson })
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent).toEqual(preparedEvent)
            expect(result.value.person).toBe(mockPerson)
            expect(result.value.processPerson).toBe(processPerson)
            expect(result.value.historicalMigration).toBe(false)
        }

        expect(mockProcessEvent).toHaveBeenCalledWith(
            mockEvent.distinct_id,
            expect.objectContaining({ ...mockEvent, team_id: mockTeam.id }),
            mockTeam,
            expect.anything(),
            mockEvent.uuid,
            processPerson,
            mockGroupStore
        )
    })

    it.each([
        { desc: 'historical_migration=true', historical_migration: true, expected: true },
        { desc: 'historical_migration=false', historical_migration: false, expected: false },
    ])('should extract historicalMigration from headers ($desc)', async ({ historical_migration, expected }) => {
        mockProcessEvent.mockResolvedValue(createTestPreIngestionEvent())
        const headers = createTestEventHeaders({ historical_migration })

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        const result = await step(createInput({ headers }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.historicalMigration).toBe(expected)
        }
    })

    it('should strip normalizedEvent from the output', async () => {
        mockProcessEvent.mockResolvedValue(createTestPreIngestionEvent())

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect('normalizedEvent' in result.value).toBe(false)
        }
    })

    it('should process AI events through processAiEvent', async () => {
        const aiEvent = createTestPluginEvent({ event: '$ai_generation' })
        const transformedEvent = createTestPluginEvent({ event: '$ai_generation', properties: { enriched: true } })
        jest.mocked(processAiEvent).mockReturnValue(transformedEvent)
        mockProcessEvent.mockResolvedValue(createTestPreIngestionEvent())

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        await step(createInput({ normalizedEvent: aiEvent }))

        expect(processAiEvent).toHaveBeenCalledWith(aiEvent)
        expect(mockProcessEvent).toHaveBeenCalledWith(
            expect.anything(),
            transformedEvent,
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything()
        )
    })

    it('should swallow processAiEvent errors and use original event', async () => {
        const aiEvent = createTestPluginEvent({ event: '$ai_generation' })
        jest.mocked(processAiEvent).mockImplementation(() => {
            throw new Error('AI processing failed')
        })
        mockProcessEvent.mockResolvedValue(createTestPreIngestionEvent())

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        const result = await step(createInput({ normalizedEvent: aiEvent }))

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockProcessEvent).toHaveBeenCalledWith(
            expect.anything(),
            aiEvent,
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything(),
            expect.anything()
        )
    })

    it('should return timestamp parsing warnings as pipeline warnings', async () => {
        jest.mocked(parseEventTimestamp).mockImplementation((_event, callback) => {
            callback?.('timestamp_in_the_future', { timestamp: '3000-01-01' })
            return DateTime.fromISO('2023-01-01T00:00:00.000Z')
        })
        mockProcessEvent.mockResolvedValue(createTestPreIngestionEvent())

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        expect(result.warnings).toEqual([{ type: 'timestamp_in_the_future', details: { timestamp: '3000-01-01' } }])
    })

    it('should propagate errors from processEvent', async () => {
        const error = new Error('Processing failed')
        mockProcessEvent.mockRejectedValue(error)

        const step = createPrepareEventStep<TestInput>(mockTeamManager, mockGroupTypeManager, mockGroupStore, {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
        })

        await expect(step(createInput())).rejects.toThrow('Processing failed')
    })
})
