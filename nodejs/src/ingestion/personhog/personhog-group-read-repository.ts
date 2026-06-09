import { GroupTypeIndex, ProjectId, TeamId } from '../../types'
import { GroupReadRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
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
        return withRetry('PersonHogGroupReadRepository.fetchGroupsByKeys', () =>
            timedGrpc(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.grpcClient.groups.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, callerTag)
            )
        )
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return withRetry('PersonHogGroupReadRepository.fetchGroupTypesByTeamIds', () =>
            timedGrpc(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.grpcClient.groups.fetchGroupTypesByTeamIds(teamIds, callerTag)
            )
        )
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return withRetry('PersonHogGroupReadRepository', () =>
            timedGrpc(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.grpcClient.groups.fetchGroupTypesByProjectIds(projectIds, callerTag)
            )
        )
    }
}
