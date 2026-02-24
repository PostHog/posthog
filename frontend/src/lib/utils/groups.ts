import { GroupsQueryResponse } from '~/queries/schema/schema-general'
import { Group } from '~/types'

export type GroupQueryResult = Pick<Group, 'group_key' | 'group_properties'>

/**
 * Maps a GroupsQueryResponse from ClickHouse to a simplified Group format.
 * This is used when fetching groups via the /query endpoint instead of the REST API.
 */
export function mapGroupQueryResponse(response: GroupsQueryResponse): GroupQueryResult[] {
    return response.results.map((row) => ({
        group_key: row[response.columns.indexOf('key')],
        group_properties: {
            name: row[response.columns.indexOf('group_name')],
        },
    }))
}
