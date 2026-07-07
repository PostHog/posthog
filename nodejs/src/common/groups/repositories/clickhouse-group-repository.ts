import { DateTime } from 'luxon'

import { GROUPS_OUTPUT, GroupsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { castTimestampOrNow } from '~/common/utils/utils'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, TeamId, TimestampFormat } from '~/types'

export class ClickhouseGroupRepository {
    constructor(private outputs: IngestionOutputs<GroupsOutput>) {}

    public async upsertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        await this.outputs.queueMessages(GROUPS_OUTPUT, [
            {
                value: Buffer.from(
                    JSON.stringify({
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        team_id: teamId,
                        group_properties: JSON.stringify(properties),
                        created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                        version,
                    })
                ),
                teamId,
            },
        ])
    }
}
