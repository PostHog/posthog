import { GroupsQueryResponse } from '~/queries/schema/schema-general'
import { Group } from '~/types'

export type GroupQueryResult = Pick<Group, 'group_key' | 'group_properties'>

/**
 * Maps a GroupsQueryResponse from ClickHouse to a simplified Group format.
 * This is used when fetching groups via the /query endpoint instead of the REST API.
 */
export function mapGroupQueryResponse(response: GroupsQueryResponse): GroupQueryResult[] {
    return response.results.map((row) => {
        const groupNameIndex = response.columns.indexOf('group_name')
        const groupNameValue = row[groupNameIndex] as { display_name: string; key: string }
        return {
            group_key: groupNameValue.key,
            group_properties: {
                name: groupNameValue.display_name,
            },
        }
    })
}
