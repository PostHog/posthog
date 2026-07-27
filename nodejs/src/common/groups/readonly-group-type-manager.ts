import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { timeoutGuard } from '~/common/utils/db/utils'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { GroupTypeToColumnIndex, GroupTypesByProjectId, ProjectId } from '~/types'

/**
 * Read-only group type manager backed by a GroupReadRepository. Provides
 * cached lookups of project → group type mappings without write capability.
 * Used by services that only need to resolve existing group types (error
 * tracking, CDP) rather than create new ones (ingestion pipeline).
 */
export class ReadOnlyGroupTypeManager {
    private loader: LazyLoader<GroupTypeToColumnIndex>

    constructor(private groupRepository: GroupReadRepository) {
        this.loader = new LazyLoader({
            name: 'ReadOnlyGroupTypeManager',
            refreshAgeMs: 30_000,
            refreshJitterMs: 0,
            loader: async (projectIds: string[]) => {
                const response: Record<string, GroupTypeToColumnIndex> = {}
                const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
                try {
                    const projectIdNumbers = projectIds.map((id) => parseInt(id) as ProjectId)
                    const groupTypesByProject = await this.groupRepository.fetchGroupTypesByProjectIds(
                        projectIdNumbers,
                        'ingestion/group-type-resolution'
                    )

                    for (const [projectIdStr, groupTypes] of Object.entries(groupTypesByProject)) {
                        const groupTypeMapping: GroupTypeToColumnIndex = {}
                        for (const groupType of groupTypes) {
                            groupTypeMapping[groupType.group_type] = groupType.group_type_index
                        }
                        response[projectIdStr] = groupTypeMapping
                    }

                    for (const projectId of projectIds) {
                        response[projectId] = response[projectId] ?? {}
                    }
                } finally {
                    clearTimeout(timeout)
                }
                return response
            },
        })
    }

    public async fetchGroupTypes(projectId: ProjectId): Promise<GroupTypeToColumnIndex> {
        return (await this.loader.get(projectId.toString())) ?? {}
    }

    public async fetchGroupTypesForProjects(projectIds: ProjectId[] | Set<ProjectId>): Promise<GroupTypesByProjectId> {
        const results = await this.loader.getMany(Array.from(projectIds).map((id) => id.toString()))

        return Object.fromEntries(
            Object.entries(results).map(([projectId, groupTypes]) => [projectId, groupTypes ?? {}])
        )
    }
}
