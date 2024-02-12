import { useActions, useValues } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PROPERTY_DEFINITIONS_PER_EVENT } from 'lib/constants'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useEffect } from 'react'
import { PropertyDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { EventDefinition, PropertyDefinition } from '~/types'

export function EventDefinitionProperties({ definition }: { definition: EventDefinition }): JSX.Element {
    const { loadPropertiesForEvent } = useActions(eventDefinitionsTableLogic)
    const { eventPropertiesCacheMap, eventDefinitionPropertiesLoading } = useValues(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration } = useValues(organizationLogic)

    useEffect(() => {
        loadPropertiesForEvent(definition)
    }, [])

    const columns: LemonTableColumns<PropertyDefinition> = [
        {
            title: 'Property',
            key: 'property',
            className: 'definition-column-name',
            render: function Render(_, _definition: PropertyDefinition) {
                return <PropertyDefinitionHeader definition={_definition} event={definition} hideIcon asLink />
            },
        },
        {
            title: 'Type',
            key: 'type',
            className: 'definition-column-type',
            render: function Render(_, _definition: PropertyDefinition) {
                return _definition.property_type ? (
                    <div className="definition-pill-value uppercase">{_definition.property_type}</div>
                ) : (
                    <span className="text-muted">—</span>
                )
            },
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      key: 'tags',
                      render: function Render(_, _definition: PropertyDefinition) {
                          return <ObjectTags tags={_definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
              ]
            : []),
        {
            title: 'Example',
            key: 'example',
            align: 'right',
            className: 'definition-example-type',
            render: function Render(_, _definition: PropertyDefinition) {
                return _definition.example ? (
                    <div className="definition-pill-value font-mono">{_definition.example}</div>
                ) : (
                    <span className="text-muted">—</span>
                )
            },
        },
    ]

    return (
        <div className="event-properties-wrapper">
            <span className="event-properties-header">Top properties</span>
            <p className="event-properties-subtext">
                Please note that description and tags are shared across events. PostHog properties are excluded from
                this list.
            </p>
            <LemonTable
                id={`event-properties-definition-table-${definition.id}`}
                data-attr="event-properties-definition-nested-table"
                columns={columns}
                className={`event-properties-definition-table-${definition.id}`}
                dataSource={eventPropertiesCacheMap?.[definition.id]?.results ?? []}
                emptyState="This event has no properties"
                nouns={['property definition', 'property definitions']}
                pagination={{
                    controlled: true,
                    pageSize: PROPERTY_DEFINITIONS_PER_EVENT,
                    currentPage: eventPropertiesCacheMap?.[definition.id]?.page ?? 1,
                    entryCount: eventPropertiesCacheMap?.[definition.id]?.count ?? 0,
                    onForward: eventPropertiesCacheMap?.[definition.id]?.next
                        ? () => {
                              loadPropertiesForEvent(definition, eventPropertiesCacheMap[definition.id].next)
                          }
                        : undefined,
                    onBackward: eventPropertiesCacheMap?.[definition.id]?.previous
                        ? () => {
                              loadPropertiesForEvent(definition, eventPropertiesCacheMap[definition.id].previous)
                          }
                        : undefined,
                }}
                loading={eventDefinitionPropertiesLoading.includes(definition.id)}
            />
        </div>
    )
}
