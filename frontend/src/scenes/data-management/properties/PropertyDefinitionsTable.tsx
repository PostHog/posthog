import './PropertyDefinitionsTable.scss'

import { LemonInput, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PropertyDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { PropertyDefinition } from '~/types'

export function PropertyDefinitionsTable(): JSX.Element {
    const { propertyDefinitions, propertyDefinitionsLoading, filters, propertyTypeOptions } =
        useValues(propertyDefinitionsTableLogic)
    const { loadPropertyDefinitions, setFilters, setPropertyType } = useActions(propertyDefinitionsTableLogic)
    const { hasDashboardCollaboration } = useValues(organizationLogic)

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
        {
            title: 'Type',
            key: 'type',
            render: function RenderType(_, definition: PropertyDefinition) {
                return definition.property_type ? (
                    <LemonTag type="success" className="uppercase">
                        {definition.property_type}
                    </LemonTag>
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
                      render: function Render(_, definition: PropertyDefinition) {
                          return <ObjectTags tags={definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<PropertyDefinition, keyof PropertyDefinition | undefined>,
              ]
            : []),
    ]

    return (
        <div data-attr="manage-events-table">
            <LemonBanner className="mb-4" type="info">
                Looking for {filters.type === 'person' ? 'person ' : ''}property usage statistics?{' '}
                <Link
                    to={urls.insightNewHogQL(
                        'SELECT arrayJoin(JSONExtractKeys(properties)) AS property_key, count()\n' +
                            (filters.type === 'person' ? 'FROM persons\n' : 'FROM events\n') +
                            (filters.type === 'person' ? '' : 'WHERE timestamp > now() - interval 1 month\n') +
                            'GROUP BY property_key\n' +
                            'ORDER BY count() DESC'
                    )}
                >
                    Click here!
                </Link>
            </LemonBanner>
            <div className="flex justify-between mb-4 gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for properties"
                    onChange={(e) => setFilters({ property: e || '' })}
                    value={filters.property}
                />
                <LemonSelect
                    options={propertyTypeOptions}
                    value={`${filters.type}::${filters.group_type_index ?? ''}`}
                    onSelect={setPropertyType}
                />
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
        </div>
    )
}
