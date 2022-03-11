import './EventPropertyDefinitionsTable.scss'
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
    const { eventPropertyDefinitions, eventPropertyDefinitionsLoading, openedDefinitionId } = useValues(
        eventPropertyDefinitionsTableLogic
    )
    const { loadEventPropertyDefinitions, setLocalEventPropertyDefinition } = useActions(
        eventPropertyDefinitionsTableLogic
    )
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<PropertyDefinition> = [
        {
            key: 'icon',
            className: 'definition-column-icon',
            render: function Render(_, definition: PropertyDefinition) {
                return <PropertyDefinitionHeader definition={definition} hideView hideText />
            },
        },
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: PropertyDefinition) {
                return (
                    <PropertyDefinitionHeader
                        definition={definition}
                        hideIcon
                        hideView
                        openDetailInNewTab={false}
                        updateRemoteItem={(nextPropertyDefinition) => {
                            setLocalEventPropertyDefinition(nextPropertyDefinition as PropertyDefinition)
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
            rowStatus={(row) => {
                return row.id === openedDefinitionId ? 'highlighted' : undefined
            }}
            pagination={{
                controlled: true,
                currentPage: eventPropertyDefinitions?.page ?? 1,
                entryCount: eventPropertyDefinitions?.count ?? 0,
                pageSize: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
                onForward: !!eventPropertyDefinitions.next
                    ? () => {
                          loadEventPropertyDefinitions(eventPropertyDefinitions.next)
                      }
                    : undefined,
                onBackward: !!eventPropertyDefinitions.previous
                    ? () => {
                          loadEventPropertyDefinitions(eventPropertyDefinitions.previous)
                      }
                    : undefined,
            }}
            dataSource={eventPropertyDefinitions.results}
            emptyState="No event property definitions"
            nouns={['property', 'properties']}
        />
    )
}
