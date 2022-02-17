import './EventDefinitionsTable.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { EventDefinition } from '~/types'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { getEventDefinitionIcon } from 'scenes/data-management/events/EventDefinitionHeader'

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
    const { hasDashboardCollaboration } = useValues(organizationLogic)

    const columns: LemonTableColumns<EventDefinition> = [
        {
            title: 'Name',
            key: 'name',
            className: 'event-definition-column-name',
            render: function Render(_, definition: EventDefinition): JSX.Element {
                console.log('DEFINITION', definition)
                return (
                    <>
                        {getEventDefinitionIcon(definition)}
                        <div className="event-definition-column-name-content">
                            {definition.name}
                            {definition.description || 'There is no description for this event'}
                        </div>
                    </>
                )
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
        {
            title: '30 day volume',
            key: '30_day_volume',
            render: function Render(_, definition: EventDefinition): JSX.Element {
                console.log('DEFINITION', definition)
                return <div>{definition.name}</div>
            },
        },
        {
            title: '30 day queries',
            key: '30_day_queries',
            render: function Render(_, definition: EventDefinition): JSX.Element {
                console.log('DEFINITION', definition)
                return <div>{definition.name}</div>
            },
        },
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
                pageSize: 100,
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
            dataSource={eventDefinitions.results}
            emptyState="No event definitions"
            nouns={['definition', 'definitions']}
        />
    )
}
