import { createTestTeam } from '../../../tests/helpers/team'
import { PreIngestionEvent, ProjectId, Team, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { PipelineResultType } from '../pipelines/results'
import { createReadOnlyProcessGroupsStep } from './readonly-process-groups-step'

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

describe('createReadOnlyProcessGroupsStep', () => {
    let mockGroupTypeManager: jest.Mocked<Pick<GroupTypeManager, 'fetchGroupTypes'>>

    beforeEach(() => {
        jest.clearAllMocks()
        mockGroupTypeManager = { fetchGroupTypes: jest.fn().mockResolvedValue({}) }
    })

    const createInput = (overrides: Partial<TestInput> = {}): TestInput => ({
        preparedEvent: createTestPreIngestionEvent(),
        team: createTestTeam(),
        processPerson: true,
        ...overrides,
    })

    it.each([
        {
            desc: 'processPerson=false skips group enrichment',
            processPerson: false,
            hasGroups: true,
            expectFetchGroupTypes: false,
        },
        {
            desc: 'processPerson=true with no $groups skips group enrichment',
            processPerson: true,
            hasGroups: false,
            expectFetchGroupTypes: false,
        },
        {
            desc: 'processPerson=true with $groups fetches group types',
            processPerson: true,
            hasGroups: true,
            expectFetchGroupTypes: true,
        },
    ])('$desc', async ({ processPerson, hasGroups, expectFetchGroupTypes }) => {
        mockGroupTypeManager.fetchGroupTypes.mockResolvedValue({ org: 0 })

        const step = createReadOnlyProcessGroupsStep<TestInput>(mockGroupTypeManager as unknown as GroupTypeManager)
        const result = await step(
            createInput({
                processPerson,
                preparedEvent: createTestPreIngestionEvent({
                    properties: hasGroups ? { $groups: { org: 'posthog' } } : {},
                }),
            })
        )

        expect(result.type).toBe(PipelineResultType.OK)
        if (expectFetchGroupTypes) {
            expect(mockGroupTypeManager.fetchGroupTypes).toHaveBeenCalled()
        } else {
            expect(mockGroupTypeManager.fetchGroupTypes).not.toHaveBeenCalled()
        }
    })

    it('enriches properties with $group_N using read-only fetch', async () => {
        mockGroupTypeManager.fetchGroupTypes.mockResolvedValue({ org: 0, project: 1 })

        const step = createReadOnlyProcessGroupsStep<TestInput>(mockGroupTypeManager as unknown as GroupTypeManager)
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

    it('skips unknown group types without writing', async () => {
        mockGroupTypeManager.fetchGroupTypes.mockResolvedValue({ org: 0 })

        const step = createReadOnlyProcessGroupsStep<TestInput>(mockGroupTypeManager as unknown as GroupTypeManager)
        const input = createInput({
            preparedEvent: createTestPreIngestionEvent({
                properties: { $groups: { org: 'posthog', unknown_type: 'value' } },
            }),
        })
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.properties).toEqual({
                $groups: { org: 'posthog', unknown_type: 'value' },
                $group_0: 'posthog',
            })
        }
    })
})
