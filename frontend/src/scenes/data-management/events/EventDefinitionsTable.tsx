import './EventDefinitionsTable.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { EventDefinition } from '~/types'
import {
    EVENT_DEFINITIONS_PER_PAGE,
    eventDefinitionsTableLogic,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { EventDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { humanFriendlyNumber } from 'lib/utils'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'

export const scene: SceneExport = {
    component: EventDefinitionsTable,
    logic: eventDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

interface EventDefinitionsTableProps {
    compact?: boolean
}

export function EventDefinitionsTable({}: EventDefinitionsTableProps = {}): JSX.Element {
    const { eventDefinitions, eventDefinitionsLoading } = useValues(eventDefinitionsTableLogic)
    const { loadEventDefinitions } = useActions(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<EventDefinition> = [
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: EventDefinition) {
                return <EventDefinitionHeader definition={definition} hideView />
            },
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      key: 'tags',
                      render: function Render(_, definition: EventDefinition) {
                          return <ObjectTags tags={definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
              ]
            : []),
        ...(hasIngestionTaxonomy
            ? [
                  {
                      title: '30 day volume',
                      key: 'volume_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.volume_30_day ? (
                              humanFriendlyNumber(definition.volume_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
                  {
                      title: '30 day queries',
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.query_usage_30_day ? (
                              humanFriendlyNumber(definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
              ]
            : []),
    ]

    return (
        <LemonTable
            columns={columns}
            className="events-definition-table"
            data-attr="events-definition-table"
            loading={eventDefinitionsLoading}
            rowKey="id"
            pagination={{
                controlled: true,
                currentPage: eventDefinitions?.page ?? 1,
                entryCount: eventDefinitions?.count ?? 0,
                pageSize: EVENT_DEFINITIONS_PER_PAGE,
                onForward: !!eventDefinitions.next
                    ? () => {
                          loadEventDefinitions(eventDefinitions.next)
                          window.scrollTo(0, 0)
                      }
                    : undefined,
                onBackward: !!eventDefinitions.previous
                    ? () => {
                          loadEventDefinitions(eventDefinitions.previous)
                          window.scrollTo(0, 0)
                      }
                    : undefined,
            }}
            expandable={{
                expandedRowRender: function RenderPropertiesTable(definition) {
                    return <EventDefinitionProperties definition={definition} />
                },
                noIndent: true,
            }}
            dataSource={eventDefinitions.results}
            emptyState="No event definitions"
            nouns={['definition', 'definitions']}
        />
    )
}
