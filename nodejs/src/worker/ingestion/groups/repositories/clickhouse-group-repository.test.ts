import { DateTime } from 'luxon'

import { GROUPS_OUTPUT, GroupsOutput } from '~/ingestion/common/outputs'
import { IngestionOutputs } from '~/ingestion/outputs/ingestion-outputs'

import { GroupTypeIndex, TeamId } from '../../../../types'
import { ClickhouseGroupRepository } from './clickhouse-group-repository'

describe('ClickhouseGroupRepository', () => {
    let mockQueueMessages: jest.Mock
    let outputs: IngestionOutputs<GroupsOutput>
    let repository: ClickhouseGroupRepository

    beforeEach(() => {
        mockQueueMessages = jest.fn().mockResolvedValue(undefined)
        outputs = {
            queueMessages: mockQueueMessages,
        } as unknown as IngestionOutputs<GroupsOutput>
        repository = new ClickhouseGroupRepository(outputs)
    })

    it('should upsert group to ClickHouse via outputs', async () => {
        const teamId = 1 as TeamId
        const groupTypeIndex = 0 as GroupTypeIndex
        const groupKey = 'test-group'
        const properties = { name: 'Test Group' }
        const createdAt = DateTime.utc()
        const version = 1

        await repository.upsertGroup(teamId, groupTypeIndex, groupKey, properties, createdAt, version)

        expect(mockQueueMessages).toHaveBeenCalledWith(GROUPS_OUTPUT, [
            {
                value: Buffer.from(
                    JSON.stringify({
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        team_id: teamId,
                        group_properties: JSON.stringify(properties),
                        created_at: createdAt.toFormat('yyyy-MM-dd HH:mm:ss'),
                        version,
                    })
                ),
                teamId,
            },
        ])
    })
})
