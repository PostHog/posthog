import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AnyResponseType, ErrorTrackingGroupsQuery, ErrorTrackingGroupsQueryResponse } from '~/queries/schema'

let uniqueNode = 0
export function ErrorTrackingGroups(props: {
    query: ErrorTrackingGroupsQuery
    cachedResults?: AnyResponseType
}): JSX.Element | null {
    const [key] = useState(() => `ErrorTracking.${uniqueNode++}`)
    const logic = dataNodeLogic({
        key,
        query: props.query,
        cachedResults: props.cachedResults,
    })
    const { response, responseLoading } = useValues(logic)

    const errorTrackingGroupsQueryResponse = response as ErrorTrackingGroupsQueryResponse | undefined

    return (
        <LemonTable
            columns={[
                {
                    dataIndex: 'title',
                    width: '50%',
                    render: (_, group) => (
                        <LemonTableLink
                            title={group.title}
                            description={<div className="line-clamp-1">{group.description}</div>}
                            to={urls.errorTrackingGroup(group.id)}
                        />
                    ),
                },
                {
                    title: 'Occurrences',
                    dataIndex: 'occurrences',
                    sorter: (a, b) => a.occurrences - b.occurrences,
                },
                {
                    title: 'Sessions',
                    dataIndex: 'uniqueSessions',
                    sorter: (a, b) => a.uniqueSessions - b.uniqueSessions,
                },
                {
                    title: 'Users',
                    dataIndex: 'uniqueUsers',
                    sorter: (a, b) => a.uniqueUsers - b.uniqueUsers,
                },
            ]}
            loading={responseLoading}
            dataSource={errorTrackingGroupsQueryResponse?.results || []}
        />
    )
}
