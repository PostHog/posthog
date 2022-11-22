import { EventsNode, EventsTableNode } from '~/queries/schema'
import { useState } from 'react'
import { EventType } from '~/types'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { LemonTable } from 'lib/components/LemonTable'

interface EventsTableQueryProps {
    query: EventsTableNode
    setQuery?: (node: EventsTableNode) => void
}

let uniqueNode = 0

export function EventsTableQuery({ query }: EventsTableQueryProps): JSX.Element {
    const [id] = useState(uniqueNode++)
    const logic = dataNodeLogic({ query: query.events, key: `EventsTableQuery.${id}` })
    const { response, responseLoading } = useValues(logic)
    const rows = (response as null | EventsNode['response'])?.results ?? []

    return (
        <LemonTable
            loading={responseLoading}
            columns={
                rows.length > 0 && Object.keys(rows[0]).length > 0
                    ? Object.keys(rows[0]).map((key) => ({ dataIndex: key as keyof EventType, title: key }))
                    : [{ dataIndex: '' as keyof EventType, title: 'Events Table' }]
            }
            dataSource={rows}
        />
    )
}
