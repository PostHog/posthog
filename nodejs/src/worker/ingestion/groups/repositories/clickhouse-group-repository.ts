import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { KAFKA_GROUPS } from '../../../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { GroupTypeIndex, TeamId, TimestampFormat } from '../../../../types'
import { castTimestampOrNow } from '../../../../utils/utils'

export class ClickhouseGroupRepository {
    constructor(private kafkaProducer: KafkaProducerWrapper) {}

    public async upsertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        await this.kafkaProducer.queueMessages({
            topic: KAFKA_GROUPS,
            messages: [
                {
                    value: JSON.stringify({
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        team_id: teamId,
                        group_properties: JSON.stringify(properties),
                        created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                        version,
                    }),
                },
            ],
        })
    }
}
