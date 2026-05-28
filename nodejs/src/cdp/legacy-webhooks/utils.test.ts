import { GroupTypeIndex, ISOTimestamp, PostIngestionEvent, ProjectId, TeamId } from '~/types'
import { TeamManager } from '~/utils/team-manager'
import { GroupTypeManager, GroupTypesByProjectId } from '~/worker/ingestion/group-type-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { addGroupPropertiesToPostIngestionEventsBatch } from './utils'

function makeEvent(teamId: number, overrides: Partial<PostIngestionEvent> = {}): PostIngestionEvent {
    return {
        eventUuid: `uuid-${Math.random()}`,
        event: '$pageview',
        teamId: teamId as TeamId,
        projectId: teamId as ProjectId,
        distinctId: 'user-1',
        properties: {},
        timestamp: '2024-01-01T00:00:00.000Z' as ISOTimestamp,
        person_created_at: null,
        person_properties: {},
        person_id: undefined,
        ...overrides,
    }
}

function makeEventWithGroups(
    teamId: number,
    groups: Record<string, string>,
    overrides: Partial<PostIngestionEvent> = {}
): PostIngestionEvent {
    return makeEvent(teamId, {
        properties: { $groups: groups },
        ...overrides,
    })
}

describe('addGroupPropertiesToPostIngestionEventsBatch', () => {
    let mockTeamManager: jest.Mocked<Pick<TeamManager, 'hasAvailableFeature'>>
    let mockGroupTypeManager: jest.Mocked<Pick<GroupTypeManager, 'fetchGroupTypesForProjects'>>
    let mockGroupRepository: jest.Mocked<Pick<GroupRepository, 'fetchGroupsByKeys'>>

    beforeEach(() => {
        mockTeamManager = {
            hasAvailableFeature: jest.fn().mockResolvedValue(false),
        }
        mockGroupTypeManager = {
            fetchGroupTypesForProjects: jest.fn().mockResolvedValue({}),
        }
        mockGroupRepository = {
            fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
        }
    })

    it('returns empty array for empty input', async () => {
        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            [],
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )
        expect(result).toEqual([])
        expect(mockTeamManager.hasAvailableFeature).not.toHaveBeenCalled()
    })

    it('returns events unchanged when no team has group_analytics', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(false)
        const events = [makeEventWithGroups(1, { project: 'p1' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result).toEqual(events)
        expect(mockGroupTypeManager.fetchGroupTypesForProjects).toHaveBeenCalledWith(new Set())
        expect(mockGroupRepository.fetchGroupsByKeys).not.toHaveBeenCalled()
    })

    it('checks group_analytics once per unique team', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({})

        const events = [makeEvent(1), makeEvent(1), makeEvent(2), makeEvent(1)]

        await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(mockTeamManager.hasAvailableFeature).toHaveBeenCalledTimes(2)
        expect(mockTeamManager.hasAvailableFeature).toHaveBeenCalledWith(1, 'group_analytics')
        expect(mockTeamManager.hasAvailableFeature).toHaveBeenCalledWith(2, 'group_analytics')
    })

    it('enriches a single event with group properties', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Inc' },
            },
        ])

        const events = [makeEventWithGroups(1, { company: 'acme' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({
            company: {
                index: 0,
                key: 'acme',
                type: 'company',
                properties: { name: 'Acme Inc' },
            },
        })
    })

    it('deduplicates identical group lookups across events', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Inc' },
            },
        ])

        const events = [
            makeEventWithGroups(1, { company: 'acme' }),
            makeEventWithGroups(1, { company: 'acme' }),
            makeEventWithGroups(1, { company: 'acme' }),
        ]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(mockGroupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)
        expect(mockGroupRepository.fetchGroupsByKeys).toHaveBeenCalledWith([1], [0], ['acme'])

        for (const event of result) {
            expect(event.groups?.company).toEqual({
                index: 0,
                key: 'acme',
                type: 'company',
                properties: { name: 'Acme Inc' },
            })
        }
    })

    it('handles multiple group types per event', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': {
                company: 0 as GroupTypeIndex,
                project: 1 as GroupTypeIndex,
            },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Inc' },
            },
            {
                team_id: 1 as TeamId,
                group_type_index: 1 as GroupTypeIndex,
                group_key: 'proj-1',
                group_properties: { name: 'Project Alpha' },
            },
        ])

        const events = [makeEventWithGroups(1, { company: 'acme', project: 'proj-1' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({
            company: {
                index: 0,
                key: 'acme',
                type: 'company',
                properties: { name: 'Acme Inc' },
            },
            project: {
                index: 1,
                key: 'proj-1',
                type: 'project',
                properties: { name: 'Project Alpha' },
            },
        })
    })

    it('handles mixed teams where only some have group_analytics', async () => {
        mockTeamManager.hasAvailableFeature.mockImplementation((teamId) => {
            return Promise.resolve(teamId === 1)
        })
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Inc' },
            },
        ])

        const events = [makeEventWithGroups(1, { company: 'acme' }), makeEventWithGroups(2, { company: 'other-co' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups?.company).toEqual({
            index: 0,
            key: 'acme',
            type: 'company',
            properties: { name: 'Acme Inc' },
        })
        expect(result[1].groups).toBeUndefined()
    })

    it('returns empty properties when group is not found', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([])

        const events = [makeEventWithGroups(1, { company: 'nonexistent' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({
            company: {
                index: 0,
                key: 'nonexistent',
                type: 'company',
                properties: {},
            },
        })
    })

    it('skips group types where event has no matching $groups key', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': {
                company: 0 as GroupTypeIndex,
                project: 1 as GroupTypeIndex,
            },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Inc' },
            },
        ])

        const events = [makeEventWithGroups(1, { company: 'acme' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({
            company: {
                index: 0,
                key: 'acme',
                type: 'company',
                properties: { name: 'Acme Inc' },
            },
        })
        expect(result[0].groups?.project).toBeUndefined()
    })

    it('sets empty groups object when team has group_analytics but event has no $groups', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)

        const events = [makeEvent(1)]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({})
        expect(mockGroupRepository.fetchGroupsByKeys).not.toHaveBeenCalled()
    })

    it('handles events with no group type mappings for their project', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({})

        const events = [makeEventWithGroups(1, { company: 'acme' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({})
        expect(mockGroupRepository.fetchGroupsByKeys).not.toHaveBeenCalled()
    })

    it('handles batch with different teams and different groups', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
            '2': { organization: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme' },
            },
            {
                team_id: 2 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'globex',
                group_properties: { name: 'Globex' },
            },
        ])

        const events = [
            makeEventWithGroups(1, { company: 'acme' }),
            makeEventWithGroups(2, { organization: 'globex' }, { projectId: 2 as ProjectId }),
        ]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups?.company?.properties).toEqual({ name: 'Acme' })
        expect(result[1].groups?.organization?.properties).toEqual({ name: 'Globex' })

        expect(mockGroupRepository.fetchGroupsByKeys).toHaveBeenCalledWith([1, 2], [0, 0], ['acme', 'globex'])
    })

    it('does not deduplicate when same group type index has different keys', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme' },
            },
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'globex',
                group_properties: { name: 'Globex' },
            },
        ])

        const events = [makeEventWithGroups(1, { company: 'acme' }), makeEventWithGroups(1, { company: 'globex' })]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(mockGroupRepository.fetchGroupsByKeys).toHaveBeenCalledWith([1, 1], [0, 0], ['acme', 'globex'])
        expect(result[0].groups?.company?.properties).toEqual({ name: 'Acme' })
        expect(result[1].groups?.company?.properties).toEqual({ name: 'Globex' })
    })

    it('treats same group key under different teams as separate lookups', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
            '2': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([
            {
                team_id: 1 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Team 1' },
            },
            {
                team_id: 2 as TeamId,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'acme',
                group_properties: { name: 'Acme Team 2' },
            },
        ])

        const events = [
            makeEventWithGroups(1, { company: 'acme' }),
            makeEventWithGroups(2, { company: 'acme' }, { projectId: 2 as ProjectId }),
        ]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(mockGroupRepository.fetchGroupsByKeys).toHaveBeenCalledWith([1, 2], [0, 0], ['acme', 'acme'])
        expect(result[0].groups?.company?.properties).toEqual({ name: 'Acme Team 1' })
        expect(result[1].groups?.company?.properties).toEqual({ name: 'Acme Team 2' })
    })

    it('handles $groups set to empty object', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)

        const events = [makeEventWithGroups(1, {})]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result[0].groups).toEqual({})
        expect(mockGroupRepository.fetchGroupsByKeys).not.toHaveBeenCalled()
    })

    it('preserves event order and non-group fields', async () => {
        mockTeamManager.hasAvailableFeature.mockResolvedValue(true)
        mockGroupTypeManager.fetchGroupTypesForProjects.mockResolvedValue({
            '1': { company: 0 as GroupTypeIndex },
        } as GroupTypesByProjectId)
        mockGroupRepository.fetchGroupsByKeys.mockResolvedValue([])

        const events = [
            makeEventWithGroups(1, { company: 'a' }, { eventUuid: 'first', distinctId: 'user-a' }),
            makeEventWithGroups(1, { company: 'b' }, { eventUuid: 'second', distinctId: 'user-b' }),
            makeEventWithGroups(1, { company: 'c' }, { eventUuid: 'third', distinctId: 'user-c' }),
        ]

        const result = await addGroupPropertiesToPostIngestionEventsBatch(
            events,
            mockGroupTypeManager as unknown as GroupTypeManager,
            mockTeamManager as unknown as TeamManager,
            mockGroupRepository as unknown as GroupRepository
        )

        expect(result.map((e) => e.eventUuid)).toEqual(['first', 'second', 'third'])
        expect(result.map((e) => e.distinctId)).toEqual(['user-a', 'user-b', 'user-c'])
    })
})
