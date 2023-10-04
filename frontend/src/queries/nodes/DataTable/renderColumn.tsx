import { AnyPropertyFilter, EventType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/lemon-ui/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { DataTableNode, EventsQueryPersonColumn, HasPropertiesNode, QueryContext } from '~/queries/schema'
import { isEventsQuery, isHogQLQuery, isPersonsNode, isTimeToSeeDataSessionsQuery, trimQuotes } from '~/queries/utils'
import { combineUrl, router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DeletePersonButton } from '~/queries/nodes/PersonsNode/DeletePersonButton'
import ReactJson from '@microlink/react-json-view'
import { errorColumn, loadingColumn } from '~/queries/nodes/DataTable/dataTableLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { TableCellSparkline } from 'lib/lemon-ui/LemonTable/TableCellSparkline'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function renderColumn(
    key: string,
    value: any,
    record: Record<string, any> | any[],
    query: DataTableNode,
    setQuery?: (query: DataTableNode) => void,
    context?: QueryContext
): JSX.Element | string {
    if (value === loadingColumn) {
        return <Spinner />
    } else if (value === errorColumn) {
        return <LemonTag color="red">Error</LemonTag>
    } else if (value === null) {
        return (
            <Tooltip title="NULL" placement="right" delayMs={0}>
                <span className="cursor-default" aria-hidden>
                    —
                </span>
            </Tooltip>
        )
    } else if (isHogQLQuery(query.source)) {
        if (typeof value === 'string') {
            try {
                if (value.startsWith('{') && value.endsWith('}')) {
                    return (
                        <ReactJson
                            src={JSON.parse(value)}
                            name={key}
                            collapsed={Object.keys(JSON.stringify(value)).length > 10 ? 0 : 1}
                        />
                    )
                }
                if (value.startsWith('[') && value.endsWith(']')) {
                    return (
                        <ReactJson
                            src={JSON.parse(value)}
                            name={key}
                            collapsed={JSON.stringify(value).length > 10 ? 0 : 1}
                        />
                    )
                }
            } catch (e) {
                // do nothing
            }
            if (value.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}/)) {
                return <TZLabel time={value} showSeconds />
            }
        }
        if (typeof value === 'object') {
            if (Array.isArray(value)) {
                if (value[0] === '__hogql_chart_type' && value[1] === 'sparkline') {
                    const object: Record<string, any> = {}
                    for (let i = 0; i < value.length; i += 2) {
                        object[value[i]] = value[i + 1]
                    }
                    if ('results' in object && Array.isArray(object.results)) {
                        return <TableCellSparkline data={object.results} />
                    }
                }

                return <ReactJson src={value} name={key} collapsed={value.length > 10 ? 0 : 1} />
            }
            return <ReactJson src={value} name={key} collapsed={Object.keys(value).length > 10 ? 0 : 1} />
        }
        return <Property value={value} />
    } else if (key === 'event' && isEventsQuery(query.source)) {
        const resultRow = record as any[]
        const eventRecord = query.source.select.includes('*') ? resultRow[query.source.select.indexOf('*')] : null

        if (value === '$autocapture' && eventRecord) {
            return autoCaptureEventToDescription(eventRecord)
        } else {
            const content = <PropertyKeyInfo value={value} type="event" />
            const $sentry_url = eventRecord?.properties?.$sentry_url
            return $sentry_url ? (
                <Link to={$sentry_url} target="_blank">
                    {content}
                </Link>
            ) : (
                content
            )
        }
    } else if (key === 'timestamp' || key === 'created_at' || key === 'session_start' || key === 'session_end') {
        return <TZLabel time={value} showSeconds />
    } else if (!Array.isArray(record) && key.startsWith('properties.')) {
        // TODO: remove after removing the old events table
        const propertyKey = trimQuotes(key.substring(11))
        if (setQuery && (isEventsQuery(query.source) || isPersonsNode(query.source)) && query.showPropertyFilter) {
            const newProperty: AnyPropertyFilter = {
                key: propertyKey,
                value: record.properties[propertyKey],
                operator: PropertyOperator.Exact,
                type: isPersonsNode(query.source) ? PropertyFilterType.Person : PropertyFilterType.Event,
            }
            const matchingProperty = (query.source.properties || []).find(
                (p) => p.key === newProperty.key && p.type === newProperty.type
            )
            const newProperties = matchingProperty
                ? (query.source.properties || []).filter((p) => p !== matchingProperty)
                : [...(query.source.properties || []), newProperty]
            const newUrl = query.propertiesViaUrl
                ? combineUrl(
                      router.values.location.pathname,
                      {
                          ...router.values.searchParams,
                          properties: newProperties,
                      },
                      router.values.hashParams
                  ).url
                : '#'
            return (
                <Link
                    className="ph-no-capture"
                    to={newUrl}
                    onClick={(e) => {
                        e.preventDefault()
                        setQuery({
                            ...query,
                            source: {
                                ...query.source,
                                properties: newProperties,
                            } as HasPropertiesNode,
                        })
                    }}
                >
                    <Property value={record.properties[propertyKey]} />
                </Link>
            )
        }
        return <Property value={record.properties[propertyKey]} />
    } else if (!Array.isArray(record) && key.startsWith('person.properties.')) {
        // TODO: remove after removing the old events table
        const eventRecord = record as EventType
        const propertyKey = trimQuotes(key.substring(18))
        if (setQuery && isEventsQuery(query.source)) {
            const newProperty: AnyPropertyFilter = {
                key: propertyKey,
                value: eventRecord.person?.properties[propertyKey],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            }
            const matchingProperty = (query.source.properties || []).find(
                (p) => p.key === newProperty.key && p.type === newProperty.type
            )
            const newProperties = matchingProperty
                ? (query.source.properties || []).filter((p) => p !== matchingProperty)
                : [...(query.source.properties || []), newProperty]
            const newUrl = query.propertiesViaUrl
                ? combineUrl(
                      router.values.location.pathname,
                      {
                          ...router.values.searchParams,
                          properties: newProperties,
                      },
                      router.values.hashParams
                  ).url
                : '#'
            return (
                <Link
                    className="ph-no-capture"
                    to={newUrl}
                    onClick={(e) => {
                        e.preventDefault()
                        setQuery({
                            ...query,
                            source: {
                                ...query.source,
                                properties: newProperties,
                            } as HasPropertiesNode,
                        })
                    }}
                >
                    <Property value={eventRecord.person?.properties?.[propertyKey]} />
                </Link>
            )
        }
        return <Property value={eventRecord.person?.properties?.[propertyKey]} />
    } else if (key === 'person' && isEventsQuery(query.source)) {
        const personRecord = value as EventsQueryPersonColumn
        return personRecord.distinct_id ? (
            <PersonDisplay withIcon person={personRecord} />
        ) : (
            <PersonDisplay noLink withIcon person={value} />
        )
    } else if (key === 'person' && isPersonsNode(query.source)) {
        const personRecord = record as PersonType
        return (
            <Link to={urls.personByDistinctId(personRecord.distinct_ids[0])}>
                <PersonDisplay noLink withIcon person={personRecord} noPopover />
            </Link>
        )
    } else if (key === 'person.$delete' && isPersonsNode(query.source)) {
        const personRecord = record as PersonType
        return <DeletePersonButton person={personRecord} />
    } else if (key.startsWith('context.columns.')) {
        const Component = context?.columns?.[trimQuotes(key.substring(16))]?.render
        return Component ? <Component record={record} /> : ''
    } else if (key === 'id' && isPersonsNode(query.source)) {
        return (
            <CopyToClipboardInline
                explicitValue={String(value)}
                iconStyle={{ color: 'var(--primary)' }}
                description="person distinct ID"
            >
                {String(value)}
            </CopyToClipboardInline>
        )
    } else if (key.startsWith('user.') && isTimeToSeeDataSessionsQuery(query.source)) {
        const [parent, child] = key.split('.')
        return typeof record === 'object' ? record[parent][child] : 'unknown'
    } else {
        if (typeof value === 'object' && value !== null) {
            return <ReactJson src={value} name={key} collapsed={Object.keys(value).length > 10 ? 0 : 1} />
        }
        return String(value)
    }
}
