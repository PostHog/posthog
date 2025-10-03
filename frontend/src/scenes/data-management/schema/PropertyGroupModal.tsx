import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SchemaPropertyGroupProperty, schemaManagementLogic } from './schemaManagementLogic'

const PROPERTY_TYPE_OPTIONS = [
    { value: 'String', label: 'String' },
    { value: 'Numeric', label: 'Numeric' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'DateTime', label: 'DateTime' },
    { value: 'Duration', label: 'Duration' },
]

export function PropertyGroupModal(): JSX.Element {
    const { propertyGroupModalOpen, editingPropertyGroup } = useValues(schemaManagementLogic)
    const { setPropertyGroupModalOpen, createPropertyGroup, updatePropertyGroup } = useActions(schemaManagementLogic)

    const [groupName, setGroupName] = useState('')
    const [groupDescription, setGroupDescription] = useState('')
    const [properties, setProperties] = useState<SchemaPropertyGroupProperty[]>([])

    useEffect(() => {
        if (propertyGroupModalOpen) {
            setGroupName(editingPropertyGroup?.name || '')
            setGroupDescription(editingPropertyGroup?.description || '')
            setProperties(editingPropertyGroup?.properties || [])
        }
    }, [propertyGroupModalOpen, editingPropertyGroup])

    const handleSave = (): void => {
        const data = {
            name: groupName,
            description: groupDescription,
            properties,
        }

        if (editingPropertyGroup) {
            updatePropertyGroup({ id: editingPropertyGroup.id, data })
        } else {
            createPropertyGroup(data)
        }
        handleClose()
    }

    const handleClose = (): void => {
        setPropertyGroupModalOpen(false)
        setGroupName('')
        setGroupDescription('')
        setProperties([])
    }

    const addProperty = (): void => {
        setProperties([
            ...properties,
            {
                id: `new-${Date.now()}`,
                name: '',
                property_type: 'String',
                is_required: false,
                description: '',
                order: properties.length,
            },
        ])
    }

    const updateProperty = (index: number, updates: Partial<SchemaPropertyGroupProperty>): void => {
        setProperties(properties.map((prop, i) => (i === index ? { ...prop, ...updates } : prop)))
    }

    const removeProperty = (index: number): void => {
        setProperties(properties.filter((_, i) => i !== index))
    }

    const columns: LemonTableColumns<SchemaPropertyGroupProperty> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, property, index) => (
                <LemonInput
                    value={property.name}
                    onChange={(value) => updateProperty(index, { name: value })}
                    placeholder="Property name"
                    fullWidth
                />
            ),
        },
        {
            title: 'Type',
            key: 'property_type',
            width: 150,
            render: (_, property, index) => (
                <LemonSelect
                    value={property.property_type}
                    onChange={(value) => updateProperty(index, { property_type: value as any })}
                    options={PROPERTY_TYPE_OPTIONS}
                    fullWidth
                />
            ),
        },
        {
            title: 'Required',
            key: 'is_required',
            width: 100,
            render: (_, property, index) => (
                <LemonButton
                    type={property.is_required ? 'primary' : 'secondary'}
                    size="small"
                    onClick={() => updateProperty(index, { is_required: !property.is_required })}
                >
                    {property.is_required ? 'Yes' : 'No'}
                </LemonButton>
            ),
        },
        {
            title: 'Description',
            key: 'description',
            render: (_, property, index) => (
                <LemonInput
                    value={property.description}
                    onChange={(value) => updateProperty(index, { description: value })}
                    placeholder="Optional description"
                    fullWidth
                />
            ),
        },
        {
            key: 'actions',
            width: 50,
            render: (_, property, index) => (
                <LemonButton icon={<IconTrash />} size="small" onClick={() => removeProperty(index)} />
            ),
        },
    ]

    return (
        <LemonModal
            isOpen={propertyGroupModalOpen}
            onClose={handleClose}
            title={editingPropertyGroup ? 'Edit Property Group' : 'New Property Group'}
            width={900}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave} disabled={!groupName.trim()}>
                        {editingPropertyGroup ? 'Update' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block mb-1 font-semibold">Name</label>
                    <LemonInput
                        value={groupName}
                        onChange={setGroupName}
                        placeholder="e.g., Order, Product, User"
                        autoFocus
                    />
                </div>

                <div>
                    <label className="block mb-1 font-semibold">Description</label>
                    <LemonTextArea
                        value={groupDescription}
                        onChange={setGroupDescription}
                        placeholder="Describe what this property group represents"
                        rows={2}
                    />
                </div>

                <div className="border-t pt-4">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-base font-semibold mb-0">Properties</h3>
                        <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={addProperty}>
                            Add property
                        </LemonButton>
                    </div>

                    {properties.length > 0 ? (
                        <LemonTable columns={columns} dataSource={properties} pagination={undefined} />
                    ) : (
                        <div className="text-center text-muted py-6">
                            No properties yet. Click "Add property" to get started.
                        </div>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
