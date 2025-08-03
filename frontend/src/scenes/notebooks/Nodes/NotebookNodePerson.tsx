import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { PropertyDefinitionType } from '~/types'
import { useActions, useValues } from 'kea'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { PersonIcon } from 'scenes/persons/PersonDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { personLogic } from 'scenes/persons/personLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { asDisplay } from 'scenes/persons/person-utils'
import { useEffect } from 'react'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import clsx from 'clsx'
import { NodeKind } from '~/queries/schema/schema-general'
import { NotFound } from 'lib/components/NotFound'
import { NotebookNodeProps, NotebookNodeType } from '../types'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonAttributes>): JSX.Element => {
    const { id } = attributes

    const logic = personLogic({ id })
    const { person, personLoading } = useValues(logic)
    const { expanded } = useValues(notebookNodeLogic)
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
                            <PropertyIcon className="text-secondary-foreground" property={property} value={value} />
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
            <div
                className={clsx(
                    'p-4 flex-0 flex gap-2 justify-between min-h-20 items-center',
                    !expanded && 'cursor-pointer'
                )}
            >
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
                            <div>
                                <span className="text-secondary-foreground">First seen:</span>{' '}
                                {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
                            </div>
                        ) : null}
                    </>
                )}
            </div>

            {expanded && (
                <>
                    <LemonDivider className="mx-2" />
                    <div className="flex-1 p-2 overflow-y-auto">
                        <PropertiesTable
                            type={PropertyDefinitionType.Person}
                            properties={person?.properties}
                            filterable
                            searchable
                        />
                    </div>
                </>
            )}
        </div>
    )
}

type NotebookNodePersonAttributes = {
    id: string
}

export const NotebookNodePerson = createPostHogWidgetNode<NotebookNodePersonAttributes>({
    nodeType: NotebookNodeType.Person,
    titlePlaceholder: 'Person',
    Component,
    heightEstimate: 300,
    minHeight: '5rem',
    startExpanded: false,
    href: (attrs) => urls.personByDistinctId(attrs.id),
    resizeable: true,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.personByDistinctId('(.+)', false),
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
    serializedText: (attrs) => {
        const personTitle = attrs?.title || ''
        const personId = attrs?.id || ''
        return `${personTitle} ${personId}`.trim()
    },
})
