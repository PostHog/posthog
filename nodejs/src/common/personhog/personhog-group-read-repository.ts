import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

import { PersonHogClient } from './client'
import { withRetry } from './grpc-retry'
import { timedGrpc } from './metrics'

/**
 * Read-only group repository backed by personhog gRPC. No Postgres
 * dependency — all reads go through personhog with automatic retries
 * on transient errors.
 */
export class PersonHogGroupReadRepository implements GroupReadRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private clientLabel: string = 'unknown'
    ) {}

    async fetchGroupsByKeys(
        teamIds: TeamId[],
        groupTypeIndexes: GroupTypeIndex[],
        groupKeys: string[],
        callerTag?: string
    ): Promise<
        {
            team_id: TeamId
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
        }[]
    > {
        const method = 'fetchGroupsByKeys'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.groups.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        const method = 'fetchGroupTypesByTeamIds'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.groups.fetchGroupTypesByTeamIds(teamIds, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        const method = 'fetchGroupTypesByProjectIds'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.groups.fetchGroupTypesByProjectIds(projectIds, callerTag)
                ),
            this.clientLabel,
            method
        )
    }
}
