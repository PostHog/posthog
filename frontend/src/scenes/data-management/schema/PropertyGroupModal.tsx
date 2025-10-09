import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { PropertyType, SchemaPropertyGroupProperty, schemaManagementLogic } from './schemaManagementLogic'

const PROPERTY_TYPE_OPTIONS: { value: PropertyType; label: string }[] = [
    { value: 'String', label: 'String' },
    { value: 'Numeric', label: 'Numeric' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'DateTime', label: 'DateTime' },
    { value: 'Duration', label: 'Duration' },
]

function isValidPropertyName(name: string): boolean {
    if (!name || !name.trim()) {
        return false
    }
    return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name.trim())
}

interface PropertyGroupModalProps {
    logicKey?: string
    onAfterSave?: () => void | Promise<void>
}

export function PropertyGroupModal({ logicKey, onAfterSave }: PropertyGroupModalProps = {}): JSX.Element {
    const logic = schemaManagementLogic({ key: logicKey || 'default' })
    const {
        propertyGroupModalOpen,
        editingPropertyGroup,
        modalFormName,
        modalFormDescription,
        modalFormProperties,
        canSaveModalForm,
        modalFormValidationIssues,
    } = useValues(logic)
    const {
        setPropertyGroupModalOpen,
        createPropertyGroup,
        updatePropertyGroup,
        setModalFormName,
        setModalFormDescription,
        addModalFormProperty,
        updateModalFormProperty,
        removeModalFormProperty,
        resetModalForm,
    } = useActions(logic)

    const handleSave = async (): Promise<void> => {
        const data = {
            name: modalFormName,
            description: modalFormDescription,
            properties: modalFormProperties.map((p) => ({ ...p, name: p.name.trim() })),
        }

        if (editingPropertyGroup) {
            await updatePropertyGroup({ id: editingPropertyGroup.id, data })
        } else {
            await createPropertyGroup(data)
        }

        handleClose()

        await onAfterSave?.()
    }

    const getSaveButtonTooltip = (): JSX.Element | undefined => {
        if (canSaveModalForm) {
            return undefined
        }
        return (
            <>
                {modalFormValidationIssues.map((issue, i) => (
                    <div key={i}>{issue}</div>
                ))}
            </>
        )
    }

    const handleClose = (): void => {
        setPropertyGroupModalOpen(false)
        resetModalForm()
    }

    const columns: LemonTableColumns<SchemaPropertyGroupProperty> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, property, index) => (
                <LemonInput
                    value={property.name}
                    onChange={(value) => updateModalFormProperty(index, { name: value })}
                    placeholder="Property name"
                    status={property.name && !isValidPropertyName(property.name) ? 'danger' : undefined}
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
                    onChange={(value) => updateModalFormProperty(index, { property_type: value as PropertyType })}
                    options={PROPERTY_TYPE_OPTIONS}
                    fullWidth
                />
            ),
        },
        {
            title: 'Required',
            key: 'is_required',
            width: 100,
            align: 'center',
            render: (_, property, index) => (
                <div
                    className="flex justify-center items-center cursor-pointer h-full py-2 -my-2"
                    onClick={() => updateModalFormProperty(index, { is_required: !property.is_required })}
                >
                    <LemonCheckbox
                        checked={property.is_required}
                        onChange={(checked) => updateModalFormProperty(index, { is_required: checked })}
                    />
                </div>
            ),
        },
        {
            title: 'Description',
            key: 'description',
            render: (_, property, index) => (
                <LemonInput
                    value={property.description}
                    onChange={(value) => updateModalFormProperty(index, { description: value })}
                    placeholder="Optional description"
                    fullWidth
                />
            ),
        },
        {
            key: 'actions',
            width: 50,
            render: (_, _property, index) => (
                <LemonButton icon={<IconTrash />} size="small" onClick={() => removeModalFormProperty(index)} />
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
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabled={!canSaveModalForm}
                        disabledReason={getSaveButtonTooltip()}
                    >
                        {editingPropertyGroup ? 'Update' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block mb-1 font-semibold">Name</label>
                    <LemonInput
                        value={modalFormName}
                        onChange={setModalFormName}
                        placeholder="e.g., Order, Product, User"
                        autoFocus
                    />
                </div>

                <div>
                    <label className="block mb-1 font-semibold">Description</label>
                    <LemonTextArea
                        value={modalFormDescription}
                        onChange={setModalFormDescription}
                        placeholder="Describe what this property group represents"
                        rows={2}
                    />
                </div>

                <div className="border-t pt-4">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-base font-semibold mb-0">Properties</h3>
                        <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={addModalFormProperty}>
                            Add property
                        </LemonButton>
                    </div>

                    {modalFormProperties.length > 0 ? (
                        <LemonTable columns={columns} dataSource={modalFormProperties} pagination={undefined} />
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
