import { AnyPropertyFilter, EventType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/lemon-ui/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { DataTableNode, HasPropertiesNode, QueryContext } from '~/queries/schema'
import { isEventsQuery, isHogQLQuery, isPersonsNode, isTimeToSeeDataSessionsQuery } from '~/queries/utils'
import { combineUrl, router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DeletePersonButton } from '~/queries/nodes/PersonsNode/DeletePersonButton'
import ReactJson from 'react-json-view'
import { errorColumn, loadingColumn } from '~/queries/nodes/DataTable/dataTableLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

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
    } else if (isHogQLQuery(query.source)) {
        if (typeof value === 'string') {
            try {
                if ((value.startsWith('{') && value.endsWith('}')) || (value.startsWith('[') && value.endsWith(']'))) {
                    return <ReactJson src={JSON.parse(value)} name={key} collapsed={1} />
                }
            } catch (e) {}
            if (value.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}/)) {
                return <TZLabel time={value} showSeconds />
            }
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
        const propertyKey = key.substring(11)
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
    } else if (key.startsWith('person.properties.')) {
        const eventRecord = record as EventType
        const propertyKey = key.substring(18)
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
        const personRecord = value as PersonType
        return !!personRecord.distinct_ids.length ? (
            <Link to={urls.person(personRecord.distinct_ids[0])}>
                <PersonHeader noLink withIcon person={personRecord} />
            </Link>
        ) : (
            <PersonHeader noLink withIcon person={value} />
        )
    } else if (key === 'person' && isPersonsNode(query.source)) {
        const personRecord = record as PersonType
        return (
            <Link to={urls.person(personRecord.distinct_ids[0])}>
                <PersonHeader noLink withIcon person={personRecord} />
            </Link>
        )
    } else if (key === 'person.$delete' && isPersonsNode(query.source)) {
        const personRecord = record as PersonType
        return <DeletePersonButton person={personRecord} />
    } else if (key.startsWith('context.columns.')) {
        const Component = context?.columns?.[key.substring(16)]?.render
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
            return <ReactJson src={value} name={key} collapsed={1} />
        }
        return String(value)
    }
}
