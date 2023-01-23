import './EventPropertyDefinitionsTable.scss'
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
} from 'scenes/data-management/properties/eventPropertyDefinitionsTableLogic'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonInput } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'
import { ThirtyDayQueryCountTitle } from 'lib/components/DefinitionPopup/DefinitionPopupContents'

export const scene: SceneExport = {
    component: EventPropertyDefinitionsTable,
    logic: eventPropertyDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventPropertyDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { eventPropertyDefinitions, eventPropertyDefinitionsLoading, filters } = useValues(
        eventPropertyDefinitionsTableLogic
    )
    const { loadEventPropertyDefinitions, setFilters } = useActions(eventPropertyDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<PropertyDefinition> = [
        {
            key: 'icon',
            className: 'definition-column-icon',
            render: function Render(_, definition: PropertyDefinition) {
                return <PropertyDefinitionHeader definition={definition} hideText />
            },
        },
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: PropertyDefinition) {
                return <PropertyDefinitionHeader definition={definition} hideIcon asLink />
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
                      title: <ThirtyDayQueryCountTitle tooltipPlacement="bottom" />,
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
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning />
            ) : (
                eventPropertyDefinitions.results?.[0]?.query_usage_30_day === null && (
                    <div className="mb-4">
                        <AlertMessage type="warning">
                            We haven't been able to get usage and volume data yet. Please check back later.
                        </AlertMessage>
                    </div>
                )
            )}
            <DataManagementPageTabs tab={DataManagementTab.EventPropertyDefinitions} />
            <div className="mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for properties"
                    onChange={(e) => setFilters({ property: e || '' })}
                    value={filters.property}
                />
            </div>

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
