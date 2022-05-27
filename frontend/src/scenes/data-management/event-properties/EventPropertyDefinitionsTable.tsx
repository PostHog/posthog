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
import { Alert, Input } from 'antd'
import { DataManagementPageHeader } from 'scenes/data-management/DataManagementPageHeader'
import { DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export const scene: SceneExport = {
    component: EventPropertyDefinitionsTable,
    logic: eventPropertyDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventPropertyDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { eventPropertyDefinitions, eventPropertyDefinitionsLoading, openedDefinitionId, filters } = useValues(
        eventPropertyDefinitionsTableLogic
    )
    const { loadEventPropertyDefinitions, setLocalEventPropertyDefinition, setFilters } = useActions(
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
                        asLink
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
        <div data-attr="manage-events-table">
            <DataManagementPageHeader activeTab={DataManagementTab.EventPropertyDefinitions} />
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Event Property Definitions" />
            ) : (
                eventPropertyDefinitions.results?.[0]?.query_usage_30_day === null && (
                    <Alert
                        type="warning"
                        message="We haven't been able to get usage and volume data yet. Please check back later."
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
                    placeholder="Search for properties"
                    allowClear
                    enterButton
                    value={filters.property}
                    style={{ maxWidth: 600, width: 'initial' }}
                    onChange={(e) => {
                        setFilters({ property: e.target.value || '' })
                    }}
                />
            </div>
            <LemonTable
                columns={columns}
                className="event-properties-definition-table"
                data-attr="event-properties-definition-table"
                loading={eventPropertyDefinitionsLoading}
                rowKey="id"
                rowStatus={(row) => {
                    return row.id === openedDefinitionId ? 'highlighted' : null
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
        </div>
    )
}
