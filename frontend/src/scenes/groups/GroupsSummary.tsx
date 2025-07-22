import { useValues } from 'kea'
import { pluralize } from 'lib/utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { GroupsQuery } from '~/queries/schema/schema-general'

import { groupsSceneLogic } from './groupsSceneLogic'
import { groupsListLogic } from './groupsListLogic'
import { GroupTypeIndex } from '~/types'

interface GroupsSummaryProps {
    query: GroupsQuery
}

export function GroupsSummary({ query }: GroupsSummaryProps): JSX.Element | null {
    const { groupTypeName, groupTypeNamePlural } = useValues(groupsSceneLogic)
    const { groupsSummaryQuery } = useValues(
        groupsListLogic({ groupTypeIndex: query.group_type_index as GroupTypeIndex })
    )

    const countKey = `GroupsSummary.${query.group_type_index}`
    const { response: countResponse, responseLoading: countLoading } = useValues(
        dataNodeLogic({
            query: groupsSummaryQuery,
            key: countKey,
            dataNodeCollectionId: countKey,
        })
    )

    const totalCount = countResponse && 'results' in countResponse ? countResponse.results?.[0]?.[0] || null : null
    const totalMrr = countResponse && 'results' in countResponse ? countResponse.results?.[0]?.[1] || null : null

    if (countLoading || totalCount === null || totalCount === 0) {
        return null
    }

    return (
        <div className="flex flex-row gap-2">
            <div>
                {pluralize(
                    totalCount,
                    groupTypeName?.toLowerCase() || 'group',
                    groupTypeNamePlural?.toLowerCase() || 'groups'
                )}
            </div>
            {totalMrr !== null && totalMrr > 0 && (
                <div className="flex flex-row gap-2">
                    <div>•</div>
                    <span>
                        ${totalMrr.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MRR
                    </span>
                </div>
            )}
        </div>
    )
}
