import { LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PROPERTY_DEFINITIONS_PER_EVENT } from 'lib/constants'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useEffect } from 'react'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { EventDefinition, PropertyDefinition } from '~/types'

import { DefinitionHeader } from './DefinitionHeader'

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
            render: function Render(_, _definition: PropertyDefinition) {
                return (
                    <DefinitionHeader
                        definition={_definition}
                        to={urls.propertyDefinition(_definition.id)}
                        taxonomicGroupType={TaxonomicFilterGroupType.EventProperties}
                    />
                )
            },
        },
        {
            title: 'Type',
            key: 'type',
            render: function Render(_, _definition: PropertyDefinition) {
                return <LemonTag type="muted">{_definition.property_type ?? '-'}</LemonTag>
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
            render: function Render(_, _definition: PropertyDefinition) {
                return (
                    <LemonTag className="font-mono" type="muted">
                        {_definition.example ?? '-'}
                    </LemonTag>
                )
            },
        },
    ]

    return (
        <div>
            <h3>Top properties</h3>
            <p>
                Please note that description and tags are shared across events. PostHog properties are excluded from
                this list.
            </p>
            <LemonTable
                id={`event-properties-definition-table-${definition.id}`}
                data-attr="event-properties-definition-nested-table"
                columns={columns}
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
