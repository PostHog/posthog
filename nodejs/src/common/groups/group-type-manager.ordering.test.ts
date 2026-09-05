import { DateTime } from 'luxon'

import { TeamManager } from '~/common/utils/team-manager'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

import { GroupTypeManager, MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { GroupRepository } from './repositories/group-repository.interface'

jest.mock('~/common/utils/posthog', () => ({
    captureTeamEvent: jest.fn(),
}))

/**
 * In-memory posthog_grouptypemapping with the same allocation semantics as
 * PostgresGroupRepository.insertGroupType: unique on (project, type) and on (project, index),
 * an existing type returns its index, a taken index moves on to the next one, and nothing
 * beyond MAX_GROUP_TYPES_PER_TEAM is ever allocated.
 */
class InMemoryGroupTypeMappings {
    private rows: { group_type: string; group_type_index: GroupTypeIndex }[] = []

    asRepository(): GroupRepository {
        return {
            fetchGroupTypesByProjectIds: (projectIds: ProjectId[]) =>
                Promise.resolve(Object.fromEntries(projectIds.map((id) => [String(id), [...this.rows]]))),
            insertGroupType: (
                _teamId: TeamId,
                projectId: ProjectId,
                groupType: string,
                index: number,
                createdAt: DateTime
            ): Promise<[GroupTypeIndex | null, boolean]> => {
                if (index < 0 || index >= MAX_GROUP_TYPES_PER_TEAM) {
                    return Promise.resolve([null, false])
                }
                const existing = this.rows.find((row) => row.group_type === groupType)
                if (existing) {
                    return Promise.resolve([existing.group_type_index, false])
                }
                if (this.rows.some((row) => row.group_type_index === index)) {
                    return this.asRepository().insertGroupType(_teamId, projectId, groupType, index + 1, createdAt)
                }
                this.rows.push({ group_type: groupType, group_type_index: index as GroupTypeIndex })
                return Promise.resolve([index as GroupTypeIndex, true])
            },
        } as unknown as GroupRepository
    }
}

describe('GroupTypeManager ordering', () => {
    const teamId: TeamId = 1
    const projectId = 1 as ProjectId
    const timestamp = DateTime.fromISO('2026-01-01T10:00:00.000Z', { zone: 'utc' })
    const teamManager = { getTeam: () => Promise.resolve(null) } as unknown as TeamManager

    async function allocateInOrder(groupTypes: string[]): Promise<Record<string, GroupTypeIndex | null>> {
        const manager = new GroupTypeManager(new InMemoryGroupTypeMappings().asRepository(), teamManager)
        const allocated: Record<string, GroupTypeIndex | null> = {}
        for (const groupType of groupTypes) {
            allocated[groupType] = await manager.fetchGroupTypeIndex(teamId, projectId, groupType, timestamp)
        }
        return allocated
    }

    // Group type slots are handed out in arrival order. Two distinct_ids introducing different
    // types are not ordered relative to each other today, so which type lands in which $group_N
    // column, and which type is dropped once the five slots are full, is already decided by
    // arrival rather than by anything the customer controls.
    it('assigns $group_N columns in arrival order, so the same types get different columns in a different order', async () => {
        const types = ['company', 'project', 'organization', 'workspace', 'account']

        const forward = await allocateInOrder(types)
        const reversed = await allocateInOrder([...types].reverse())

        expect(forward).toEqual({ company: 0, project: 1, organization: 2, workspace: 3, account: 4 })
        expect(reversed).toEqual({ account: 0, workspace: 1, organization: 2, project: 3, company: 4 })
    })

    it('drops whichever type arrives sixth, so the set of surviving types depends on order', async () => {
        const types = ['company', 'project', 'organization', 'workspace', 'account', 'channel']

        const forward = await allocateInOrder(types)
        const reversed = await allocateInOrder([...types].reverse())

        expect(forward.channel).toBeNull()
        expect(forward.company).not.toBeNull()
        expect(reversed.company).toBeNull()
        expect(reversed.channel).not.toBeNull()
    })
})
