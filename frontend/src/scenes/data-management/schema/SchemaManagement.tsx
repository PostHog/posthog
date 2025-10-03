import { useActions, useValues } from 'kea'

import { IconApps, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PropertyGroupModal } from './PropertyGroupModal'
import { SchemaPropertyGroup, SchemaPropertyGroupProperty, schemaManagementLogic } from './schemaManagementLogic'

function PropertyRow({ property }: { property: SchemaPropertyGroupProperty }): JSX.Element {
    return (
        <div className="flex items-center gap-4 py-3 px-4 border-b last:border-b-0 bg-white">
            <div className="flex-1">
                <span className="font-semibold">{property.name}</span>
            </div>
            <div className="w-32">
                <LemonTag type="muted">{property.property_type}</LemonTag>
            </div>
            <div className="w-24">
                {property.is_required ? (
                    <LemonTag type="danger">Required</LemonTag>
                ) : (
                    <LemonTag type="muted">Optional</LemonTag>
                )}
            </div>
            <div className="flex-1 text-muted">{property.description || '—'}</div>
        </div>
    )
}

export function SchemaManagement(): JSX.Element {
    const { filteredPropertyGroups, propertyGroupsLoading, searchTerm } = useValues(schemaManagementLogic)
    const { setSearchTerm, setPropertyGroupModalOpen, setEditingPropertyGroup, deletePropertyGroup } =
        useActions(schemaManagementLogic)

    const columns: LemonTableColumns<SchemaPropertyGroup> = [
        {
            key: 'expander',
            width: 0,
        },
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
            render: (name) => <span className="font-semibold">{name}</span>,
        },
        {
            title: 'Description',
            key: 'description',
            dataIndex: 'description',
            render: (description) => <span className="text-muted">{description || '—'}</span>,
        },
        {
            title: 'Properties',
            key: 'property_count',
            width: 120,
            render: (_, propertyGroup) => (
                <LemonTag type="default">
                    {propertyGroup.properties?.length || 0}{' '}
                    {propertyGroup.properties?.length === 1 ? 'property' : 'properties'}
                </LemonTag>
            ),
        },
        {
            key: 'actions',
            width: 100,
            render: (_, propertyGroup) => (
                <div className="flex gap-1">
                    <LemonButton
                        icon={<IconPencil />}
                        size="small"
                        onClick={() => {
                            setEditingPropertyGroup(propertyGroup)
                            setPropertyGroupModalOpen(true)
                        }}
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        status="danger"
                        onClick={() => {
                            if (
                                confirm(
                                    `Are you sure you want to delete "${propertyGroup.name}"? This action cannot be undone.`
                                )
                            ) {
                                deletePropertyGroup(propertyGroup.id)
                            }
                        }}
                    />
                </div>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Schema Management"
                description="Define reusable property groups to establish schemas for your events."
                resourceType={{
                    type: 'schema',
                    forceIcon: <IconApps />,
                }}
            />
            <SceneDivider />
            <div className="space-y-4">
                <div className="flex items-center justify-between gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search property groups..."
                        className="max-w-60"
                        value={searchTerm}
                        onChange={setSearchTerm}
                    />
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => {
                            setEditingPropertyGroup(null)
                            setPropertyGroupModalOpen(true)
                        }}
                    >
                        New Property Group
                    </LemonButton>
                </div>

                <LemonTable
                    columns={columns}
                    dataSource={filteredPropertyGroups}
                    loading={propertyGroupsLoading}
                    expandable={{
                        expandedRowRender: (propertyGroup) => (
                            <div className="border rounded overflow-hidden mx-4 mb-2">
                                {propertyGroup.properties && propertyGroup.properties.length > 0 ? (
                                    <>
                                        <div className="flex gap-4 py-2 px-4 bg-accent-3000 border-b text-xs font-semibold uppercase tracking-wider">
                                            <div className="flex-1">Property</div>
                                            <div className="w-32">Type</div>
                                            <div className="w-24">Required</div>
                                            <div className="flex-1">Description</div>
                                        </div>
                                        {propertyGroup.properties.map((property) => (
                                            <PropertyRow key={property.id} property={property} />
                                        ))}
                                    </>
                                ) : (
                                    <div className="text-center text-muted py-4">No properties defined</div>
                                )}
                            </div>
                        ),
                        rowExpandable: () => true,
                        indentSize: 0,
                    }}
                    emptyState="No property groups yet. Create one to get started!"
                />
            </div>

            <PropertyGroupModal />
        </SceneContent>
    )
}
