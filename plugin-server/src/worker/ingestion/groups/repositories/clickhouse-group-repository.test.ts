import { DateTime } from 'luxon'

import { KAFKA_GROUPS } from '~/config/kafka-topics'

import { GroupTypeIndex, TeamId } from '../../../../types'
import { ClickhouseGroupRepository } from './clickhouse-group-repository'

describe('ClickhouseGroupRepository', () => {
    let kafkaProducer: any
    let repository: ClickhouseGroupRepository

    beforeEach(() => {
        kafkaProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        }
        repository = new ClickhouseGroupRepository(kafkaProducer)
    })

    it('should upsert group to ClickHouse via Kafka', async () => {
        const teamId = 1 as TeamId
        const groupTypeIndex = 0 as GroupTypeIndex
        const groupKey = 'test-group'
        const properties = { name: 'Test Group' }
        const createdAt = DateTime.utc()
        const version = 1

        await repository.upsertGroup(teamId, groupTypeIndex, groupKey, properties, createdAt, version)

        expect(kafkaProducer.queueMessages).toHaveBeenCalledWith({
            topic: KAFKA_GROUPS,
            messages: [
                {
                    value: JSON.stringify({
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        team_id: teamId,
                        group_properties: JSON.stringify(properties),
                        created_at: createdAt.toFormat('yyyy-MM-dd HH:mm:ss'),
                        version,
                    }),
                },
            ],
        })
    })
})
