import { DateTime } from 'luxon'

import { GROUPS_OUTPUT, GroupsOutput } from '~/outputs'
import { IngestionOutputs } from '~/outputs/ingestion-outputs'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, TeamId, TimestampFormat } from '~/types'
import { castTimestampOrNow } from '~/utils/utils'

export type GroupClickhouseMessage = {
    output: GroupsOutput
    value: Buffer
}

export class ClickhouseGroupRepository {
    constructor(private outputs: IngestionOutputs<GroupsOutput>) {}

    public buildUpsertMessage(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): GroupClickhouseMessage {
        return {
            output: GROUPS_OUTPUT,
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
        }
    }

    public async upsertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        const message = this.buildUpsertMessage(teamId, groupTypeIndex, groupKey, properties, createdAt, version)
        await this.outputs.queueMessages(GROUPS_OUTPUT, [
            {
                value: message.value,
                teamId,
            },
        ])
    }
}
