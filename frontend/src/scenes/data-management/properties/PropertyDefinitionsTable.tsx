import './PropertyDefinitionsTable.scss'

import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { DefinitionHeader, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { verifiedFilterFromOption, verifiedFilterValue, verifiedOptions } from 'scenes/data-management/utils'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { PropertyDefinition } from '~/types'

const USAGE_RESOURCE_LABELS: Record<string, string> = {
    insights: 'insights',
    cohorts: 'cohorts',
    feature_flags: 'feature flags',
    experiments: 'experiments',
    surveys: 'surveys',
    hog_functions: 'destinations',
    hog_flows: 'workflows',
}

const IN_USE_FILTER_OPTIONS = [
    { label: 'Any', value: 'any' },
    { label: 'In use', value: 'in_use' },
    { label: 'Not in use', value: 'not_in_use' },
]

function inUseFilterValue(inUse: boolean | undefined): string {
    return inUse === undefined ? 'any' : inUse ? 'in_use' : 'not_in_use'
}

function inUseFilterFromOption(option: string): boolean | undefined {
    return option === 'any' ? undefined : option === 'in_use'
}

export function PropertyDefinitionsTable(): JSX.Element {
    const {
        propertyDefinitions,
        propertyDefinitionsLoading,
        filters,
        propertyTypeOptions,
        showVerifiedFilter,
        usageSummary,
        usageSummaryLoading,
    } = useValues(propertyDefinitionsTableLogic)
    const { loadPropertyDefinitions, setFilters, setPropertyType } = useActions(propertyDefinitionsTableLogic)

    const columns: LemonTableColumns<PropertyDefinition> = [
        {
            key: 'icon',
            width: 0,
            render: function Render(_, definition: PropertyDefinition) {
                return <span className="text-xl text-secondary">{getPropertyDefinitionIcon(definition)}</span>
            },
        },
        {
            title: 'Name',
            key: 'name',
            render: function Render(_, definition: PropertyDefinition) {
                return (
                    <div className="flex items-center gap-2">
                        <DefinitionHeader
                            definition={definition}
                            to={urls.propertyDefinition(definition.id)}
                            taxonomicGroupType={TaxonomicFilterGroupType.EventProperties}
                        />
                        {definition.warehouse_origin && (
                            <Tooltip
                                title={`Populated from data warehouse${
                                    definition.warehouse_origin.table_name
                                        ? ` table ${definition.warehouse_origin.table_name}`
                                        : ''
                                }${
                                    definition.warehouse_origin.last_synced_at
                                        ? ` (last synced ${definition.warehouse_origin.last_synced_at})`
                                        : ''
                                }`}
                            >
                                <LemonTag type="completion">Warehouse</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                )
            },
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Type',
            key: 'type',
            render: function RenderType(_, definition: PropertyDefinition) {
                return definition.property_type ? (
                    <LemonTag type="success" className="uppercase">
                        {definition.property_type}
                    </LemonTag>
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
        },
        {
            title: 'Tags',
            key: 'tags',
            render: function Render(_, definition: PropertyDefinition) {
                return <ObjectTags tags={definition.tags ?? []} staticOnly />
            },
        } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
        {
            title: (
                <span className="flex items-center gap-1">
                    Usage
                    <Tooltip title="Saved insights, cohorts, feature flags, experiments, surveys, destinations, and workflows that reference this property.">
                        <span className="text-secondary text-sm">?</span>
                    </Tooltip>
                </span>
            ),
            key: 'usage',
            render: function RenderUsage(_, definition: PropertyDefinition) {
                if (definition.virtual) {
                    return <span className="text-secondary">–</span>
                }
                const entry = usageSummary?.entries[definition.name]
                if (!entry) {
                    return usageSummaryLoading ? <Spinner /> : <span className="text-secondary">–</span>
                }
                if (entry.total_usage === 0) {
                    return (
                        <Tooltip title="Not referenced by any saved insights, cohorts, feature flags, experiments, surveys, destinations, or workflows.">
                            <span className="text-secondary">Not in use</span>
                        </Tooltip>
                    )
                }
                return (
                    <Link to={urls.propertyDefinition(definition.id)} className="flex flex-wrap gap-1">
                        {Object.entries(entry.usage)
                            .filter(([, count]) => count > 0)
                            .map(([resource, count]) => (
                                <LemonTag key={resource}>
                                    {count} {USAGE_RESOURCE_LABELS[resource] ?? resource}
                                </LemonTag>
                            ))}
                    </Link>
                )
            },
        },
        ...(filters.type === 'person'
            ? [
                  {
                      title: (
                          <span className="flex items-center gap-1">
                              Profiles
                              <Tooltip
                                  title={`Share of person profiles with this property${
                                      usageSummary?.profilesTotal
                                          ? `, out of ${humanFriendlyNumber(usageSummary.profilesTotal)} profiles`
                                          : ''
                                  }. Updated daily.`}
                              >
                                  <span className="text-secondary text-sm">?</span>
                              </Tooltip>
                          </span>
                      ),
                      key: 'profiles',
                      render: function RenderProfiles(_: unknown, definition: PropertyDefinition) {
                          const entry = usageSummary?.entries[definition.name]
                          if (!entry) {
                              return usageSummaryLoading ? <Spinner /> : <span className="text-secondary">–</span>
                          }
                          return entry.profiles_percentage != null ? (
                              <span>{entry.profiles_percentage}%</span>
                          ) : (
                              <span className="text-secondary">–</span>
                          )
                      },
                  } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
              ]
            : []),
    ]

    return (
        <SceneContent data-attr="manage-events-table">
            <SceneTitleSection
                name={sceneConfigurations[Scene.PropertyDefinition].name}
                description={sceneConfigurations[Scene.PropertyDefinition].description}
                resourceType={{
                    type: sceneConfigurations[Scene.PropertyDefinition].iconType || 'default_icon_type',
                }}
            />
            <LemonBanner type="info">
                Looking for {filters.type === 'person' ? 'person ' : ''}property usage statistics?{' '}
                <Link
                    to={urls.insightNewHogQL({
                        query:
                            'SELECT arrayJoin(JSONExtractKeys(properties)) AS property_key, count()\n' +
                            (filters.type === 'person' ? 'FROM persons\n' : 'FROM events\n') +
                            (filters.type === 'person' ? '' : 'WHERE {filters}\n') +
                            'GROUP BY property_key\n' +
                            'ORDER BY count() DESC',
                        filters: { dateRange: { date_from: '-24h' } },
                    })}
                >
                    Query with SQL
                </Link>
            </LemonBanner>
            <div className={cn('flex flex-wrap justify-between items-center gap-2')}>
                <LemonInput
                    type="search"
                    placeholder="Search for properties"
                    onChange={(e) => setFilters({ property: e || '' })}
                    value={filters.property}
                    className="flex-1 min-w-60"
                />
                <div className="flex items-center gap-2 flex-shrink-0">
                    <LemonSelect
                        options={propertyTypeOptions}
                        value={`${filters.type}::${filters.group_type_index ?? ''}`}
                        onSelect={setPropertyType}
                    />
                    <span>Usage:</span>
                    <LemonSelect
                        value={inUseFilterValue(filters.in_use)}
                        options={IN_USE_FILTER_OPTIONS}
                        data-attr="property-in-use-filter"
                        dropdownMatchSelectWidth={false}
                        onChange={(value) => {
                            setFilters({ in_use: inUseFilterFromOption(value) })
                        }}
                        size="small"
                    />
                    {showVerifiedFilter && (
                        <>
                            <span>Status:</span>
                            <LemonSelect
                                value={verifiedFilterValue(filters.verified)}
                                options={verifiedOptions}
                                data-attr="property-verified-filter"
                                dropdownMatchSelectWidth={false}
                                onChange={(value) => {
                                    setFilters({
                                        verified: verifiedFilterFromOption(value),
                                    })
                                }}
                                size="small"
                            />
                        </>
                    )}
                </div>
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
                    onForward: propertyDefinitions.next
                        ? () => {
                              loadPropertyDefinitions(propertyDefinitions.next)
                          }
                        : undefined,
                    onBackward: propertyDefinitions.previous
                        ? () => {
                              loadPropertyDefinitions(propertyDefinitions.previous)
                          }
                        : undefined,
                }}
                dataSource={propertyDefinitions.results}
                emptyState="No property definitions"
                nouns={['property', 'properties']}
            />
        </SceneContent>
    )
}
