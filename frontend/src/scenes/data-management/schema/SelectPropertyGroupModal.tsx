import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

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

interface SelectPropertyGroupModalProps {
    isOpen: boolean
    onClose: () => void
    onSelect: (propertyGroupId: string) => void
    availablePropertyGroups: SchemaPropertyGroup[]
    selectedPropertyGroupIds?: Set<string>
    onPropertyGroupCreated?: () => void
}

export function SelectPropertyGroupModal({
    isOpen,
    onClose,
    onSelect,
    availablePropertyGroups,
    selectedPropertyGroupIds = new Set(),
    onPropertyGroupCreated,
}: SelectPropertyGroupModalProps): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const logic = schemaManagementLogic({ key: 'select-property-group-modal' })
    const { setPropertyGroupModalOpen } = useActions(logic)
    const { propertyGroups } = useValues(logic)
    const previousPropertyGroupsLength = useRef(propertyGroups.length)

    // Detect when a new property group is created and notify parent
    useEffect(() => {
        if (propertyGroups.length > previousPropertyGroupsLength.current && onPropertyGroupCreated) {
            onPropertyGroupCreated()
        }
        previousPropertyGroupsLength.current = propertyGroups.length
    }, [propertyGroups.length, onPropertyGroupCreated])

    const filteredPropertyGroups = availablePropertyGroups.filter(
        (group) =>
            !selectedPropertyGroupIds.has(group.id) &&
            (searchTerm === '' || group.name.toLowerCase().includes(searchTerm.toLowerCase()))
    )

    const handleCreateNewGroup = (): void => {
        setPropertyGroupModalOpen(true)
    }

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
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => {
                        onSelect(propertyGroup.id)
                        onClose()
                    }}
                >
                    Add
                </LemonButton>
            ),
        },
    ]

    return (
        <>
            <LemonModal isOpen={isOpen} onClose={onClose} title="Add property group" width={900}>
                <div className="space-y-4">
                    <div className="flex gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search property groups..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            className="flex-1"
                            autoFocus
                        />
                        <LemonButton type="primary" icon={<IconPlus />} onClick={handleCreateNewGroup}>
                            New Property Group
                        </LemonButton>
                    </div>

                    <LemonTable
                        columns={columns}
                        dataSource={filteredPropertyGroups}
                        expandable={{
                            expandedRowRender: (propertyGroup) => (
                                <div className="border rounded overflow-hidden mx-4 mb-2 mt-2">
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
                        }}
                        emptyState={
                            searchTerm
                                ? 'No property groups match your search'
                                : 'No property groups available. Create one in Schema Management first.'
                        }
                    />
                </div>
            </LemonModal>
            <PropertyGroupModal logicKey="select-property-group-modal" />
        </>
    )
}
