import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { compactNumber } from 'lib/utils'
import { formatCurrency } from 'lib/utils/geography/currency'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { PersonIcon } from 'scenes/persons/PersonDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { personLogic } from 'scenes/persons/personLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { PersonType } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { DataSourceIcon } from './components/DataSourceIcon'
import { notebookNodeLogic } from './notebookNodeLogic'
import { OPTIONAL_PROJECT_NON_CAPTURE_GROUP } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element => {
    const { id, distinctId } = attributes

    const personLogicProps = { id, distinctId }
    const mountedPersonLogic = personLogic(personLogicProps)
    const { person, personLoading } = useValues(mountedPersonLogic)
    const { setExpanded, setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { notebookLogic } = useValues(notebookNodeLogic)
    useAttachedLogic(mountedPersonLogic, notebookLogic)

    useEffect(() => {
        const title = person ? `Person: ${asDisplay(person)}` : 'Person'
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
                            <PersonInfo />
                        </>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}

function PersonInfo(): JSX.Element | null {
    const { person } = useValues(personLogic)

    if (!person) {
        return null
    }

    return (
        <div className="flex flex-col">
            <FirstSeen person={person} />
            <LastSeen />
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

function LastSeen(): JSX.Element {
    const { info, infoLoading } = useValues(personLogic)
    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Last seen:</span>{' '}
            {infoLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : info?.lastSeen ? (
                <TZLabel time={info.lastSeen} />
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
    const { revenueData, revenueDataLoading, isRevenueAnalyticsEnabled } = useValues(personLogic)
    const { baseCurrency } = useValues(teamLogic)

    if (!isRevenueAnalyticsEnabled) {
        return null
    }

    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">MRR:</span>{' '}
            {revenueDataLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : revenueData?.mrr ? (
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
    const { revenueData, revenueDataLoading, isRevenueAnalyticsEnabled } = useValues(personLogic)
    const { baseCurrency } = useValues(teamLogic)

    if (!isRevenueAnalyticsEnabled) {
        return null
    }

    return (
        <div className="flex items-center gap-1">
            <span className="text-secondary">Lifetime value:</span>{' '}
            {revenueDataLoading ? (
                <LemonSkeleton className="h-4 w-24" />
            ) : revenueData?.lifetimeValue ? (
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
}

export const NotebookNodePerson = createPostHogWidgetNode<NotebookNodePersonAttributes>({
    nodeType: NotebookNodeType.Person,
    titlePlaceholder: 'Person',
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
    },
    pasteOptions: {
        find: OPTIONAL_PROJECT_NON_CAPTURE_GROUP + urls.personByUUID('(.+)', false),
        getAttributes: async (match) => {
            return { distinctId: undefined, id: match[1] }
        },
    },
    serializedText: (attrs) => {
        const personTitle = attrs?.title || ''
        const personId = attrs?.id || ''
        return `${personTitle} ${personId}`.trim()
    },
})
