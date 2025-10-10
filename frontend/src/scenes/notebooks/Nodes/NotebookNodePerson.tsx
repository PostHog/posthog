import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { compactNumber } from 'lib/utils'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { PersonIcon } from 'scenes/persons/PersonDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { personLogic } from 'scenes/persons/personLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import { OPTIONAL_PROJECT_NON_CAPTURE_GROUP } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element => {
    const { id, distinctId } = attributes

    const logic = personLogic({ distinctId, id })
    const { info, infoLoading, person, personLoading } = useValues(logic)
    const { setExpanded, setActions, insertAfter } = useActions(notebookNodeLogic)
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

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
        <div className="flex flex-col overflow-hidden">
            <div className={clsx('p-4 flex-0 flex flex-col gap-2 justify-between min-h-20 items-start')}>
                {personLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : (
                    <>
                        <div className="flex gap-2">
                            <PersonIcon person={person} size="xl" />
                            <div>
                                <div className="font-semibold">{asDisplay(person)}</div>
                                <div>{propertyIcons}</div>
                            </div>
                        </div>

                        {person ? (
                            <div className="flex flex-col">
                                <div className="flex items-center gap-1">
                                    <span className="text-secondary">First seen:</span>{' '}
                                    {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
                                </div>
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
                            </div>
                        ) : null}
                    </>
                )}
            </div>
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
    minHeight: '10rem',
    expandable: false,
    href: (attrs) => {
        if (attrs.distinctId) {
            return urls.personByDistinctId(attrs.distinctId)
        }
        if (attrs.id) {
            return urls.personByUUID(attrs.id)
        }
    },
    resizeable: true,
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
