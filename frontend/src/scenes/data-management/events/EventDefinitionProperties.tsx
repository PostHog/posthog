import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import {
    eventDefinitionsTableLogic,
    PROPERTY_DEFINITIONS_PER_EVENT,
    PropertyDefinitionWithExample,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { EventDefinition } from '~/types'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { DefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { humanFriendlyNumber } from 'lib/utils'

export function EventDefinitionProperties({ definition }: { definition: EventDefinition }): JSX.Element {
    const { loadPropertiesForEvent } = useActions(eventDefinitionsTableLogic)
    const { eventPropertiesCacheMap, eventPropertiesCacheMapLoading } = useValues(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    useEffect(() => {
        loadPropertiesForEvent(definition)
    }, [])

    console.log('CACHE MAP', eventPropertiesCacheMap)

    if (!(eventPropertiesCacheMap?.[definition.id]?.count > 0)) {
        return <>This event has no properties.</>
    }

    const columns: LemonTableColumns<PropertyDefinitionWithExample> = [
        {
            title: 'Property',
            key: 'property',
            className: 'definition-column-name',
            render: function Render(_, _definition: PropertyDefinitionWithExample) {
                return <DefinitionHeader definition={_definition} hideIcon />
            },
        },
        {
            title: 'Type',
            key: 'type',
            className: 'definition-column-type',
            render: function Render(_, _definition: PropertyDefinitionWithExample) {
                return _definition.property_type ? (
                    <div className="definition-pill-value" style={{ textTransform: 'uppercase' }}>
                        {_definition.property_type}
                    </div>
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
                      render: function Render(_, _definition: PropertyDefinitionWithExample) {
                          return <ObjectTags tags={_definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<PropertyDefinitionWithExample, keyof PropertyDefinitionWithExample | undefined>,
              ]
            : []),
        ...(hasIngestionTaxonomy
            ? [
                  {
                      title: '30 day queries',
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, _definition: PropertyDefinitionWithExample) {
                          return _definition.query_usage_30_day ? (
                              humanFriendlyNumber(_definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                  } as LemonTableColumn<PropertyDefinitionWithExample, keyof PropertyDefinitionWithExample | undefined>,
              ]
            : []),
        {
            title: 'Example',
            key: 'example',
            align: 'right',
            className: 'definition-example-type',
            render: function Render(_, _definition: PropertyDefinitionWithExample) {
                return _definition.example ? (
                    <div className="definition-pill-value" style={{ fontFamily: 'monospace' }}>
                        {_definition.example}
                    </div>
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
                Please note that description and tags are shared across events. Posthog properties are excluded from
                this list.
            </p>
            <LemonTable
                id={`event-properties-definition-table-${definition.id}`}
                columns={columns}
                className={`event-properties-definition-table-${definition.id}`}
                dataSource={eventPropertiesCacheMap?.[definition.id]?.results}
                emptyState="This event has no properties"
                nouns={['definition', 'definitions']}
                pagination={{
                    pageSize: PROPERTY_DEFINITIONS_PER_EVENT,
                }}
                loading={eventPropertiesCacheMapLoading}
            />
        </div>
    )
}
