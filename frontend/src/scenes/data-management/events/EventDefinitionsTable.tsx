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
import { Alert, Input } from 'antd'
import { DataManagementPageHeader } from 'scenes/data-management/DataManagementPageHeader'
import { DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { ThirtyDayQueryCountTitle, ThirtyDayVolumeTitle } from 'lib/components/DefinitionPopup/DefinitionPopupContents'

export const scene: SceneExport = {
    component: EventDefinitionsTable,
    logic: eventDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, eventDefinitionsLoading, openedDefinitionId, filters } =
        useValues(eventDefinitionsTableLogic)
    const { loadEventDefinitions, setOpenedDefinition, setFilters } = useActions(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<EventDefinition> = [
        {
            key: 'icon',
            className: 'definition-column-icon',
            render: function Render(_, definition: EventDefinition) {
                return <EventDefinitionHeader definition={definition} hideText />
            },
        },
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: EventDefinition) {
                return <EventDefinitionHeader definition={definition} hideIcon asLink />
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
                      title: <ThirtyDayVolumeTitle tooltipPlacement="bottom" />,
                      key: 'volume_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.volume_30_day ? (
                              humanFriendlyNumber(definition.volume_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: (a, b) => (a?.volume_30_day ?? 0) - (b?.volume_30_day ?? 0),
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
                  {
                      title: <ThirtyDayQueryCountTitle tooltipPlacement="bottom" />,
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.query_usage_30_day ? (
                              humanFriendlyNumber(definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: (a, b) => (a?.query_usage_30_day ?? 0) - (b?.query_usage_30_day ?? 0),
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
              ]
            : []),
    ]

    return (
        <div data-attr="manage-events-table">
            <DataManagementPageHeader activeTab={DataManagementTab.EventDefinitions} />
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Event Definitions" />
            ) : (
                eventDefinitions.results?.[0]?.volume_30_day === null && (
                    <Alert
                        type="warning"
                        message="We haven't been able to get usage and volume data yet. Please check later."
                        style={{ marginBottom: '1rem' }}
                    />
                )
            )}
            <div
                style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '0.5rem',
                    flexDirection: 'row',
                    alignItems: 'center',
                    width: '100%',
                    marginBottom: '1rem',
                }}
            >
                <Input.Search
                    placeholder="Search for events"
                    allowClear
                    enterButton
                    value={filters.event}
                    style={{ maxWidth: 600, width: 'initial' }}
                    onChange={(e) => {
                        setFilters({ event: e.target.value || '' })
                    }}
                />
            </div>
            <LemonTable
                columns={columns}
                className="events-definition-table"
                data-attr="events-definition-table"
                loading={eventDefinitionsLoading}
                rowKey="id"
                rowStatus={(row) => {
                    return row.id === openedDefinitionId ? 'highlighted' : null
                }}
                pagination={{
                    controlled: true,
                    currentPage: eventDefinitions?.page ?? 1,
                    entryCount: eventDefinitions?.count ?? 0,
                    pageSize: EVENT_DEFINITIONS_PER_PAGE,
                    onForward: !!eventDefinitions.next
                        ? () => {
                              loadEventDefinitions(eventDefinitions.next)
                          }
                        : undefined,
                    onBackward: !!eventDefinitions.previous
                        ? () => {
                              loadEventDefinitions(eventDefinitions.previous)
                          }
                        : undefined,
                }}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable(definition) {
                        return <EventDefinitionProperties definition={definition} />
                    },
                    noIndent: true,
                    isRowExpanded: (record) => (record.id === openedDefinitionId ? true : -1),
                    onRowCollapse: (record) => record.id === openedDefinitionId && setOpenedDefinition(null),
                }}
                dataSource={eventDefinitions.results}
                emptyState="No event definitions"
                nouns={['event', 'events']}
            />
        </div>
    )
}
