import './PropertyDefinitionsTable.scss'
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
    propertyDefinitionsTableLogic,
} from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'
import { ThirtyDayQueryCountTitle } from 'lib/components/DefinitionPopup/DefinitionPopupContents'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const scene: SceneExport = {
    component: PropertyDefinitionsTable,
    logic: propertyDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function PropertyDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, propertyDefinitionsLoading, filters, propertyTypeOptions } =
        useValues(propertyDefinitionsTableLogic)
    const { loadPropertyDefinitions, setFilters, setPropertyType } = useActions(propertyDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
                propertyDefinitions.results?.[0]?.query_usage_30_day === null && (
                    <div className="mb-4">
                        <AlertMessage type="warning">
                            We haven't been able to get usage and volume data yet. Please check back later.
                        </AlertMessage>
                    </div>
                )
            )}
            <DataManagementPageTabs tab={DataManagementTab.PropertyDefinitions} />
            <div className="flex justify-between mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for properties"
                    onChange={(e) => setFilters({ property: e || '' })}
                    value={filters.property}
                />
                {featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS] && (
                    <LemonSelect
                        options={propertyTypeOptions}
                        value={`${filters.type}::${filters.group_type_index ?? ''}`}
                        onSelect={setPropertyType}
                    />
                )}
            </div>

            <LemonTable
                columns={columns}
                className="event-properties-definition-table"
                data-attr="event-properties-definition-table"
                loading={propertyDefinitionsLoading}
                rowKey="id"
                pagination={{
                    controlled: true,
                    currentPage: propertyDefinitions?.page ?? 1,
                    entryCount: propertyDefinitions?.count ?? 0,
                    pageSize: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
                    onForward: !!propertyDefinitions.next
                        ? () => {
                              loadPropertyDefinitions(propertyDefinitions.next)
                          }
                        : undefined,
                    onBackward: !!propertyDefinitions.previous
                        ? () => {
                              loadPropertyDefinitions(propertyDefinitions.previous)
                          }
                        : undefined,
                }}
                dataSource={propertyDefinitions.results}
                emptyState="No event property definitions"
                nouns={['property', 'properties']}
            />
        </div>
    )
}
