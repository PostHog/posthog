import { AnyPropertyFilter, EventType, PropertyFilterType, PropertyOperator } from '~/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { TZLabel } from 'lib/components/TZLabel'
import { Property } from 'lib/components/Property'
import { urls } from 'scenes/urls'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { DataTableNode } from '~/queries/schema'
import { isEventsNode } from '~/queries/utils'
import { combineUrl, router } from 'kea-router'

export function renderColumn(
    key: string,
    record: EventType,
    query: DataTableNode,
    setQuery?: (node: DataTableNode) => void
): JSX.Element | string {
    if (key === 'event') {
        if (record.event === '$autocapture') {
            return autoCaptureEventToDescription(record)
        } else {
            const content = <PropertyKeyInfo value={record.event} type="event" />
            const { $sentry_url } = record.properties
            return $sentry_url ? (
                <Link to={$sentry_url} target="_blank">
                    {content}
                </Link>
            ) : (
                content
            )
        }
    } else if (key === 'timestamp') {
        return <TZLabel time={record.timestamp} showSeconds />
    } else if (key.startsWith('properties.')) {
        const propertyKey = key.substring(11)
        if (setQuery && isEventsNode(query.source)) {
            const newProperty: AnyPropertyFilter = {
                key: propertyKey,
                value: record.properties[propertyKey],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            }
            const matchingProperty = (query.source.properties || []).find(
                (p) => p.key === newProperty.key && p.type === newProperty.type
            )
            const newProperties = matchingProperty
                ? (query.source.properties || []).filter((p) => p !== matchingProperty)
                : [...(query.source.properties || []), newProperty]
            const newUrl = query.urlProperties
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
        const propertyKey = key.substring(18)
        if (setQuery && isEventsNode(query.source)) {
            const newProperty: AnyPropertyFilter = {
                key: propertyKey,
                value: record.person?.properties[propertyKey],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            }
            const matchingProperty = (query.source.properties || []).find(
                (p) => p.key === newProperty.key && p.type === newProperty.type
            )
            const newProperties = matchingProperty
                ? (query.source.properties || []).filter((p) => p !== matchingProperty)
                : [...(query.source.properties || []), newProperty]
            const newUrl = query.urlProperties
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
                    <Property value={record.person?.properties?.[propertyKey]} />
                </Link>
            )
        }
        return <Property value={record.person?.properties?.[propertyKey]} />
    } else if (key === 'person') {
        return (
            <Link to={urls.person(record.distinct_id)}>
                <PersonHeader noLink withIcon person={record.person} />
            </Link>
        )
    } else {
        return String(record[key])
    }
}
