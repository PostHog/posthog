import { DataTableColumn, DataTableNode, DataTableStringColumn, EventsNode } from '~/queries/schema'
import { useState } from 'react'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { LemonTable } from 'lib/components/LemonTable'
import { normalizeDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { EventType, PropertyFilterType } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { Link } from 'lib/components/Link'
import { Property } from 'lib/components/Property'
import { TZLabel } from 'lib/components/TZLabel'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

let uniqueNode = 0
export const defaultDataTableStringColumns: DataTableStringColumn[] = [
    'meta.event',
    'person',
    'event.$browser',
    'person.email',
    'meta.timestamp',
]
export const defaultDataTableColumns: DataTableColumn[] = normalizeDataTableColumns(defaultDataTableStringColumns)

function renderTitle(type: PropertyFilterType, key: string): JSX.Element | string {
    if (type === PropertyFilterType.Meta) {
        if (key === 'timestamp') {
            return 'Time'
        }
        return key
    } else if (type === PropertyFilterType.Event || type === PropertyFilterType.Element) {
        return <PropertyKeyInfo value={key} type={type} />
    } else if (type === PropertyFilterType.Person) {
        if (key === '') {
            return 'Person'
        } else {
            return <PropertyKeyInfo value={key} type="event" />
        }
    } else {
        return String(type)
    }
}

function renderColumn(type: PropertyFilterType, key: string, record: EventType): JSX.Element | string {
    if (type === PropertyFilterType.Meta) {
        if (key === 'event') {
            if (record.event === '$autocapture') {
                return autoCaptureEventToDescription(record)
            } else {
                const content = <PropertyKeyInfo value={record.event} type="event" />
                const url = record.properties.$sentry_url
                return url ? (
                    <Link to={url} target="_blank">
                        {content}
                    </Link>
                ) : (
                    content
                )
            }
        } else if (key === 'timestamp') {
            return <TZLabel time={record.timestamp} showSeconds />
        }
    } else if (type === PropertyFilterType.Person) {
        if (key === '') {
            return (
                <Link to={urls.person(record.distinct_id)}>
                    <PersonHeader noLink withIcon person={record.person} />
                </Link>
            )
        } else {
            return <Property value={record.person?.properties[key]} />
        }
    } else if (type === PropertyFilterType.Event) {
        return <Property value={record.properties[key]} />
    }
    return <div>Unknown</div>
}

export function DataTable({ query }: DataTableProps): JSX.Element {
    const columns = query.columns ? normalizeDataTableColumns(query.columns) : defaultDataTableColumns
    const [id] = useState(uniqueNode++)
    const logic = dataNodeLogic({ query: query.events, key: `DataTable.${id}` })
    const { response, responseLoading } = useValues(logic)
    const rows = (response as null | EventsNode['response'])?.results ?? []

    return (
        <LemonTable
            loading={responseLoading}
            columns={columns.map(({ type, key }) => ({
                dataIndex: `${type}.${key}` as any,
                title: renderTitle(type, key),
                render: function RenderDataTableColumn(_: any, record: EventType) {
                    return renderColumn(type, key, record)
                },
            }))}
            dataSource={rows}
        />
    )
}
