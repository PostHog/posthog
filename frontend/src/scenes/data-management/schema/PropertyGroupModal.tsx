import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
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
        propertyGroupForm,
        isPropertyGroupFormSubmitting,
        propertyGroupFormValidationError,
    } = useValues(logic)
    const {
        setPropertyGroupModalOpen,
        addPropertyToForm,
        updatePropertyInForm,
        removePropertyFromForm,
        submitPropertyGroupForm,
    } = useActions(logic)

    const handleClose = (): void => {
        setPropertyGroupModalOpen(false)
    }

    const handleAfterSubmit = async (): Promise<void> => {
        await onAfterSave?.()
    }

    const columns: LemonTableColumns<SchemaPropertyGroupProperty> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, property, index) => (
                <LemonInput
                    value={property.name}
                    onChange={(value) => updatePropertyInForm(index, { name: value })}
                    placeholder="Property name"
                    status={!isValidPropertyName(property.name) ? 'danger' : undefined}
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
                    onChange={(value) => updatePropertyInForm(index, { property_type: value as PropertyType })}
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
                    onClick={() => updatePropertyInForm(index, { is_required: !property.is_required })}
                >
                    <LemonCheckbox
                        checked={property.is_required}
                        onChange={(checked) => updatePropertyInForm(index, { is_required: checked })}
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
                    onChange={(value) => updatePropertyInForm(index, { description: value })}
                    placeholder="Optional description"
                    fullWidth
                />
            ),
        },
        {
            key: 'actions',
            width: 50,
            render: (_, _property, index) => (
                <LemonButton icon={<IconTrash />} size="small" onClick={() => removePropertyFromForm(index)} />
            ),
        },
    ]

    return (
        <LemonModal
            isOpen={propertyGroupModalOpen}
            onClose={handleClose}
            title={editingPropertyGroup ? 'Edit Property Group' : 'New Property Group'}
            width={900}
        >
            <Form
                logic={schemaManagementLogic}
                props={{ key: logicKey || 'default' }}
                formKey="propertyGroupForm"
                enableFormOnSubmit
                className="space-y-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g., Order, Product, User" autoFocus />
                </LemonField>

                <LemonField name="description" label="Description">
                    <LemonTextArea placeholder="Describe what this property group represents" rows={2} />
                </LemonField>

                <div className="border-t pt-4">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="text-base font-semibold mb-0">Properties</h3>
                        <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={addPropertyToForm}>
                            Add property
                        </LemonButton>
                    </div>

                    {propertyGroupForm.properties.length > 0 ? (
                        <>
                            <LemonTable
                                columns={columns}
                                dataSource={propertyGroupForm.properties}
                                pagination={undefined}
                            />
                            {propertyGroupFormValidationError && (
                                <div className="text-danger text-sm mt-2">{propertyGroupFormValidationError}</div>
                            )}
                        </>
                    ) : (
                        <div className="text-center text-muted py-6">
                            No properties yet. Click "Add property" to get started.
                        </div>
                    )}
                </div>

                <div className="flex justify-end gap-2 pt-4 border-t">
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isPropertyGroupFormSubmitting}
                        disabledReason={propertyGroupFormValidationError || undefined}
                        onClick={async () => {
                            await submitPropertyGroupForm()
                            await handleAfterSubmit()
                        }}
                    >
                        {editingPropertyGroup ? 'Update' : 'Create'}
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
