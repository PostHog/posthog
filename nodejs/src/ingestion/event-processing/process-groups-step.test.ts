import { DateTime } from 'luxon'

import { createTestTeam } from '../../../tests/helpers/team'
import { PreIngestionEvent, ProjectId, Team, TimestampFormat } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PipelineResultType } from '../pipelines/results'
import { createProcessGroupsStep } from './process-groups-step'

const createTestPreIngestionEvent = (overrides: Partial<PreIngestionEvent> = {}): PreIngestionEvent => ({
    eventUuid: 'test-uuid',
    event: '$pageview',
    teamId: 1,
    projectId: 1 as ProjectId,
    distinctId: 'test-distinct-id',
    properties: {},
    timestamp: castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ISO),
    ...overrides,
})

type TestInput = {
    preparedEvent: PreIngestionEvent
    team: Team
    processPerson: boolean
}

describe('createProcessGroupsStep', () => {
    let mockTeamManager: jest.Mocked<Pick<TeamManager, 'setTeamIngestedEvent'>>
    let mockGroupTypeManager: jest.Mocked<Pick<GroupTypeManager, 'fetchGroupTypeIndex'>>
    let mockGroupStore: jest.Mocked<Pick<BatchWritingGroupStore, 'upsertGroup'>>

    beforeEach(() => {
        jest.clearAllMocks()

        mockTeamManager = { setTeamIngestedEvent: jest.fn().mockResolvedValue(undefined) }
        mockGroupTypeManager = { fetchGroupTypeIndex: jest.fn().mockResolvedValue(null) }
        mockGroupStore = { upsertGroup: jest.fn().mockResolvedValue(undefined) }
    })

    const createInput = (overrides: Partial<TestInput> = {}): TestInput => ({
        preparedEvent: createTestPreIngestionEvent(),
        team: createTestTeam(),
        processPerson: true,
        ...overrides,
    })

    const createStep = (skipUpdate = false) =>
        createProcessGroupsStep<TestInput>(
            mockTeamManager as unknown as TeamManager,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockGroupStore as unknown as BatchWritingGroupStore,
            { SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: skipUpdate }
        )

    it.each([
        {
            desc: 'processPerson=false skips all group operations',
            processPerson: false,
            properties: { $groups: { org: 'posthog' } },
            expectGroupTypeIndexCalls: 0,
        },
        {
            desc: 'processPerson=true resolves group types via fetchGroupTypeIndex',
            processPerson: true,
            properties: { $groups: { org: 'posthog' } },
            expectGroupTypeIndexCalls: 1,
        },
        {
            desc: 'processPerson=true with no $groups skips group resolution',
            processPerson: true,
            properties: {},
            expectGroupTypeIndexCalls: 0,
        },
    ])('$desc', async ({ processPerson, properties, expectGroupTypeIndexCalls }) => {
        const step = createStep()
        const result = await step(
            createInput({ processPerson, preparedEvent: createTestPreIngestionEvent({ properties }) })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockGroupTypeManager.fetchGroupTypeIndex).toHaveBeenCalledTimes(expectGroupTypeIndexCalls)
    })

    it('enriches properties with $group_N when $groups is present', async () => {
        mockGroupTypeManager.fetchGroupTypeIndex
            .mockResolvedValueOnce(0) // org
            .mockResolvedValueOnce(1) // project
        const step = createStep()
        const input = createInput({
            preparedEvent: createTestPreIngestionEvent({
                properties: { $groups: { org: 'posthog', project: 'posthog-js' } },
            }),
        })
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.properties).toEqual({
                $groups: { org: 'posthog', project: 'posthog-js' },
                $group_0: 'posthog',
                $group_1: 'posthog-js',
            })
        }
    })

    it('calls upsertGroup for $groupidentify events', async () => {
        mockGroupTypeManager.fetchGroupTypeIndex.mockResolvedValue(0)

        const step = createStep()
        const result = await step(
            createInput({
                preparedEvent: createTestPreIngestionEvent({
                    event: '$groupidentify',
                    properties: {
                        $group_type: 'organization',
                        $group_key: 'org::5',
                        $group_set: { foo: 'bar' },
                    },
                }),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockGroupStore.upsertGroup).toHaveBeenCalledWith(1, 1, 0, 'org::5', { foo: 'bar' }, expect.any(DateTime))
    })

    it.each([
        {
            desc: 'missing $group_type',
            properties: { $group_key: 'org::5', $group_set: { foo: 'bar' } },
        },
        {
            desc: 'missing $group_key',
            properties: { $group_type: 'organization', $group_set: { foo: 'bar' } },
        },
    ])('does not call upsertGroup for $groupidentify when $desc', async ({ properties }) => {
        mockGroupTypeManager.fetchGroupTypeIndex.mockResolvedValue(0)

        const step = createStep()
        const result = await step(
            createInput({
                preparedEvent: createTestPreIngestionEvent({ event: '$groupidentify', properties }),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockGroupStore.upsertGroup).not.toHaveBeenCalled()
    })

    it('does not call upsertGroup when group type index is null', async () => {
        mockGroupTypeManager.fetchGroupTypeIndex.mockResolvedValue(null)

        const step = createStep()
        const result = await step(
            createInput({
                preparedEvent: createTestPreIngestionEvent({
                    event: '$groupidentify',
                    properties: {
                        $group_type: 'organization',
                        $group_key: 'org::5',
                        $group_set: { foo: 'bar' },
                    },
                }),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockGroupStore.upsertGroup).not.toHaveBeenCalled()
    })

    it('does not call upsertGroup for non-$groupidentify events', async () => {
        const step = createStep()
        await step(createInput())

        expect(mockGroupStore.upsertGroup).not.toHaveBeenCalled()
    })

    it('skips updateGroupsAndFirstEvent when SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP=true', async () => {
        const step = createStep(true)
        await step(createInput())

        expect(mockTeamManager.setTeamIngestedEvent).not.toHaveBeenCalled()
    })

    it('calls updateGroupsAndFirstEvent when SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP=false', async () => {
        const step = createStep()
        await step(createInput())

        expect(mockTeamManager.setTeamIngestedEvent).toHaveBeenCalled()
    })

    it('swallows updateGroupsAndFirstEvent errors and continues processing', async () => {
        mockTeamManager.setTeamIngestedEvent.mockRejectedValue(new Error('DB error'))

        const step = createStep()
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('skips updateGroupsAndFirstEvent for $$plugin_metrics events', async () => {
        const step = createStep()
        await step(
            createInput({
                preparedEvent: createTestPreIngestionEvent({ event: '$$plugin_metrics' }),
            })
        )

        expect(mockTeamManager.setTeamIngestedEvent).not.toHaveBeenCalled()
    })
})
