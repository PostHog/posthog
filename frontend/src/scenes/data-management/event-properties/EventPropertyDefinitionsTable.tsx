import './EventDefinitionsTable.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { PropertyDefinition } from '~/types'
import { SceneExport } from 'scenes/sceneTypes'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { PropertyDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { humanFriendlyNumber } from 'lib/utils'
import {
    EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
    eventPropertyDefinitionsTableLogic,
} from 'scenes/data-management/event-properties/eventPropertyDefinitionsTableLogic'

export const scene: SceneExport = {
    component: EventPropertyDefinitionsTable,
    logic: eventPropertyDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventPropertyDefinitionsTable(): JSX.Element {
    const { eventPropertyDefinitions, eventPropertyDefinitionsLoading } = useValues(eventPropertyDefinitionsTableLogic)
    const { loadEventPropertyDefinitions, setLocalEventPropertyDefinition } = useActions(
        eventPropertyDefinitionsTableLogic
    )
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<PropertyDefinition> = [
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: PropertyDefinition) {
                return (
                    <PropertyDefinitionHeader
                        definition={definition}
                        hideView
                        updateRemoteItem={(nextPropertyDefinition) => {
                            setLocalEventPropertyDefinition(nextPropertyDefinition)
                        }}
                    />
                )
            },
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      key: 'tags',
                      render: function Render(_, definition: PropertyDefinition) {
                          return <ObjectTags tags={definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
              ]
            : []),
        ...(hasIngestionTaxonomy
            ? [
                  {
                      title: '30 day queries',
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, definition: PropertyDefinition) {
                          return definition.query_usage_30_day ? (
                              humanFriendlyNumber(definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: (a, b) => (a?.query_usage_30_day ?? 0) - (b?.query_usage_30_day ?? 0),
                  } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
              ]
            : []),
    ]

    return (
        <LemonTable
            columns={columns}
            className="event-properties-definition-table"
            data-attr="event-properties-definition-table"
            loading={eventPropertyDefinitionsLoading}
            rowKey="id"
            pagination={{
                controlled: true,
                currentPage: eventPropertyDefinitions?.page ?? 1,
                entryCount: eventPropertyDefinitions?.count ?? 0,
                pageSize: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
                onForward: !!eventPropertyDefinitions.next
                    ? () => {
                          loadEventPropertyDefinitions(eventPropertyDefinitions.next)
                          window.scrollTo(0, 0)
                      }
                    : undefined,
                onBackward: !!eventPropertyDefinitions.previous
                    ? () => {
                          loadEventPropertyDefinitions(eventPropertyDefinitions.previous)
                          window.scrollTo(0, 0)
                      }
                    : undefined,
            }}
            dataSource={eventPropertyDefinitions.results}
            emptyState="No event property definitions"
            nouns={['property', 'properties']}
        />
    )
}
