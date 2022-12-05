import { AnyPropertyFilter, EventType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { DataTableNode, QueryCustom } from '~/queries/schema'
import { isEventsNode, isPersonsNode } from '~/queries/utils'
import { combineUrl, router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export function renderColumn(
    key: string,
    record: EventType | PersonType,
    query: DataTableNode,
    setQuery?: (node: DataTableNode) => void,
    custom?: QueryCustom
): JSX.Element | string {
    if (key === 'event' && isEventsNode(query.source)) {
        const eventRecord = record as EventType
        if (eventRecord.event === '$autocapture') {
            return autoCaptureEventToDescription(eventRecord)
        } else {
            const content = <PropertyKeyInfo value={eventRecord.event} type="event" />
            const { $sentry_url } = eventRecord.properties
            return $sentry_url ? (
                <Link to={$sentry_url} target="_blank">
                    {content}
                </Link>
            ) : (
                content
            )
        }
    } else if (key === 'timestamp' || key === 'created_at') {
        return <TZLabel time={record[key]} showSeconds />
    } else if (key.startsWith('properties.') || key === 'url') {
        const propertyKey =
            key === 'url' ? (record.properties['$screen_name'] ? '$screen_name' : '$current_url') : key.substring(11)
        if (setQuery && (isEventsNode(query.source) || isPersonsNode(query.source)) && query.showPropertyFilter) {
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
                            },
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
        if (setQuery && isEventsNode(query.source)) {
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
                            },
                        })
                    }}
                >
                    <Property value={eventRecord.person?.properties?.[propertyKey]} />
                </Link>
            )
        }
        return <Property value={eventRecord.person?.properties?.[propertyKey]} />
    } else if (key === 'person' && isEventsNode(query.source)) {
        const eventRecord = record as EventType
        return (
            <Link to={urls.person(eventRecord.distinct_id)}>
                <PersonHeader noLink withIcon person={eventRecord.person} />
            </Link>
        )
    } else if (key === 'person' && isPersonsNode(query.source)) {
        const personRecord = record as PersonType
        return (
            <Link to={urls.person(personRecord.distinct_ids[0])}>
                <PersonHeader noLink withIcon person={personRecord} />
            </Link>
        )
    } else if (key.startsWith('custom.')) {
        const Component = custom?.[key.substring(7)]?.render
        return Component ? <Component record={record} /> : ''
    } else if (key === 'id' && isPersonsNode(query.source)) {
        return (
            <CopyToClipboardInline
                explicitValue={record[key]}
                iconStyle={{ color: 'var(--primary)' }}
                description="person distinct ID"
            >
                {record[key]}
            </CopyToClipboardInline>
        )
    } else {
        return String(record[key])
    }
}
