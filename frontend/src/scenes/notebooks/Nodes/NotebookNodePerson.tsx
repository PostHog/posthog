import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { formatCurrency } from 'lib/utils/currency'
import { compactNumber } from 'lib/utils/numbers'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { defineNotebookWidgetViews, getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonIcon } from 'scenes/persons/PersonDisplay'
import { personLogic } from 'scenes/persons/personLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { PersonType } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { DataSourceIcon } from './components/DataSourceIcon'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = (props: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element => {
    return <PersonCard {...props} compact={false} />
}

function PersonCard({
    attributes,
    compact,
}: NotebookNodeProps<NotebookNodePersonAttributes> & { compact: boolean }): JSX.Element {
    const { id, distinctId } = attributes

    const personLogicProps = { id, distinctId }
    const mountedPersonLogic = personLogic(personLogicProps)
    const { person, personLoading } = useValues(mountedPersonLogic)
    const { setExpanded, setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { notebookLogic } = useValues(notebookNodeLogic)
    useAttachedLogic(mountedPersonLogic, notebookLogic)

    useEffect(() => {
        const title = person ? asDisplay(person) : 'Person'
        setTitlePlaceholder(title)
        setActions([
            {
                text: 'Events',
                onClick: () => {
                    setExpanded(false)
                    insertAfter({
                        type: NotebookNodeType.Query,
                        attrs: {
                            title: `Events for ${title}`,
                            query: {
                                kind: NodeKind.DataTableNode,
                                source: {
                                    kind: NodeKind.EventsQuery,
                                    select: [
                                        '*',
                                        'event',
                                        'person',
                                        'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                                        'properties.$lib',
                                        'timestamp',
                                    ],
                                    personId: person?.uuid,
                                    after: '-24h',
                                },
                            },
                        },
                    })
                },
            },
        ])
        // oxlint-disable-next-line exhaustive-deps
    }, [person])

    const iconPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
    const iconProperties = person?.properties || {}

    const propertyIcons = (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1 h-4 ph-no-capture">
            {!personLoading ? (
                iconPropertyKeys.map((property) => {
                    let value = iconProperties?.[property]
                    if (property === '$device_type') {
                        value = iconProperties?.['$device_type'] || iconProperties?.['$initial_device_type']
                    }

                    let tooltipValue = value
                    if (property === '$geoip_country_code') {
                        tooltipValue = `${iconProperties?.['$geoip_country_name']} (${value})`
                    }

                    return (
                        <Tooltip
                            key={property}
                            title={
                                <div className="text-center">
                                    <span className="font-medium">{tooltipValue ?? 'N/A'}</span>
                                </div>
                            }
                        >
                            <PropertyIcon className="text-secondary" property={property} value={value} />
                        </Tooltip>
                    )
                })
            ) : (
                <LemonSkeleton className="h-4 w-18 my-1" />
            )}
        </div>
    )

    if (!person && !personLoading) {
        return <NotFound object="person" />
    }

    return (
        <BindLogic logic={personLogic} props={personLogicProps}>
            <div className="flex flex-1 flex-col overflow-auto">
                <div className={clsx('p-4 flex-0 flex flex-col gap-2 justify-between min-h-20 items-start')}>
                    {personLoading ? (
                        <LemonSkeleton className="h-6" />
                    ) : (
                        <>
                            <div className="flex gap-2">
                                <PersonIcon person={person} size="xl" />
                                <div>
                                    <div className="font-semibold ph-no-capture">{asDisplay(person)}</div>
                                    <div>{propertyIcons}</div>
                                </div>
                            </div>
                            {!compact ? <PersonInfo /> : null}
                        </>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}

function PersonInfo(): JSX.Element | null {
    const { person } = useValues(personLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!person) {
        return null
    }

    return (
        <div className="flex flex-col">
            <FirstSeen person={person} />
            {currentTeam?.extra_settings?.person_last_seen_at_enabled === true && <LastSeen />}
            <MRR />
            <LifetimeValue />
            <SessionCount />
            <EventCount />
        </div>
    )
}

function FirstSeen({ person }: { person: PersonType }): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">First seen:</span>{' '}
            {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
        </div>
    )
}

// `last_seen_at` is floored to the hour, so for a person whose first and last activity
// fall in the same hour it can resolve to *before* `created_at`. Clamp to `created_at` so
// "Last seen" never appears earlier than "First seen" — the real last activity is within
// the rounding hour of first seen anyway.
function clampLastSeenToFirstSeen(lastSeenAt: string, createdAt?: string): dayjs.Dayjs {
    const lastSeen = dayjs(lastSeenAt)
    if (!createdAt) {
        return lastSeen
    }
    const firstSeen = dayjs(createdAt)
    return lastSeen.isBefore(firstSeen) ? firstSeen : lastSeen
}

function LastSeen(): JSX.Element {
    const { person, personLoading } = useValues(personLogic)
    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Last seen:</span>{' '}
            {personLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : person?.last_seen_at ? (
                <TZLabel time={clampLastSeenToFirstSeen(person.last_seen_at, person.created_at)} />
            ) : (
                'unknown'
            )}
        </div>
    )
}

function SessionCount(): JSX.Element {
    const { info, infoLoading } = useValues(personLogic)
    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Session count (30d):</span>{' '}
            {infoLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : info?.sessionCount ? (
                compactNumber(info.sessionCount)
            ) : (
                'unknown'
            )}
        </div>
    )
}

function EventCount(): JSX.Element {
    const { info, infoLoading } = useValues(personLogic)
    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Event count (30d):</span>{' '}
            {infoLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : info?.eventCount ? (
                compactNumber(info.eventCount)
            ) : (
                'unknown'
            )}
        </div>
    )
}

function MRR(): JSX.Element | null {
    const { revenueData, revenueDataLoading } = useValues(personLogic)
    const { baseCurrency } = useValues(teamLogic)

    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">MRR:</span>{' '}
            {revenueDataLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : revenueData?.mrr != null ? (
                <div className="flex gap-2 items-center">
                    {formatCurrency(revenueData.mrr, baseCurrency)}
                    <DataSourceIcon source="revenue-analytics" />
                </div>
            ) : (
                'unknown'
            )}
        </div>
    )
}

function LifetimeValue(): JSX.Element | null {
    const { revenueData, revenueDataLoading } = useValues(personLogic)
    const { baseCurrency } = useValues(teamLogic)

    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Lifetime value:</span>{' '}
            {revenueDataLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : revenueData?.lifetimeValue != null ? (
                <div className="flex gap-2 items-center">
                    {formatCurrency(revenueData.lifetimeValue, baseCurrency)}
                    <DataSourceIcon source="revenue-analytics" />
                </div>
            ) : (
                'unknown'
            )}
        </div>
    )
}

type NotebookNodePersonAttributes = {
    id: string | undefined
    distinctId: string | undefined
    view?: string
}

function PersonSummary(props: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element {
    return <PersonCard {...props} compact />
}

function PersonActivity({ attributes }: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element {
    const personLogicProps = { id: attributes.id, distinctId: attributes.distinctId }
    const { person, personLoading } = useValues(personLogic(personLogicProps))
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { notebookLogic } = useValues(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(person ? asDisplay(person) : 'Person')
    }, [person, setTitlePlaceholder])

    if (!person && !personLoading) {
        return <NotFound object="person" />
    }
    if (!person) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }

    return (
        <BindLogic logic={personLogic} props={personLogicProps}>
            <Query
                uniqueKey={`${attributes.nodeId}-activity`}
                attachTo={notebookLogic}
                query={{
                    kind: NodeKind.DataTableNode,
                    embedded: true,
                    full: false,
                    source: {
                        kind: NodeKind.EventsQuery,
                        personId: person.uuid,
                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                        after: '-30d',
                        limit: 50,
                    },
                }}
                readOnly
            />
        </BindLogic>
    )
}

const PERSON_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<NotebookNodePersonAttributes, 'Person'>('Person', {
    summary: PersonSummary,
    activity: PersonActivity,
})

export const NotebookNodePerson = createPostHogWidgetNode<NotebookNodePersonAttributes>({
    nodeType: NotebookNodeType.Person,
    titlePlaceholder: 'Person',
    editableTitle: false,
    Component,
    expandable: false,
    href: (attrs) => {
        if (attrs.distinctId) {
            return urls.personByDistinctId(attrs.distinctId)
        }
        if (attrs.id) {
            return urls.personByUUID(attrs.id)
        }
    },
    resizeable: false,
    attributes: {
        id: {},
        distinctId: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Person'),
    views: PERSON_NOTEBOOK_WIDGET_VIEWS,
    serializedText: (attrs) => attrs.title || 'Person',
})
