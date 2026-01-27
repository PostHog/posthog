import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { PropertyDefinition, materializedColumnsLogic } from './materializedColumnsLogic'

export function CreateSlotModal(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { availableProperties, availablePropertiesLoading } = useValues(materializedColumnsLogic)
    const { setShowCreateModal, loadSlots } = useActions(materializedColumnsLogic)
    const [selectedPropertyId, setSelectedPropertyId] = useState<number | null>(null)
    const [searchTerm, setSearchTerm] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)

    const handleSubmit = async (): Promise<void> => {
        if (!currentTeam || !selectedPropertyId) {
            return
        }

        setIsSubmitting(true)
        try {
            await api.create(`api/environments/${currentTeam.id}/materialized_column_slots/assign_slot/`, {
                property_definition_id: selectedPropertyId,
            })
            lemonToast.success('Slot assigned successfully')
            setShowCreateModal(false)
            loadSlots()
        } catch (error: any) {
            lemonToast.error(error.detail || 'Failed to assign slot')
            console.error(error)
        } finally {
            setIsSubmitting(false)
        }
    }

    // Filter and sort properties based on search term
    const filteredProperties = availableProperties
        .filter((prop: PropertyDefinition) => prop.name.toLowerCase().includes(searchTerm.toLowerCase()))
        .sort((a: PropertyDefinition, b: PropertyDefinition) => a.name.localeCompare(b.name))

    const selectedProperty = availableProperties.find((prop: PropertyDefinition) => prop.id === selectedPropertyId)

    return (
        <LemonModal
            isOpen
            onClose={() => setShowCreateModal(false)}
            title="Assign Materialized Column Slot"
            width="36rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setShowCreateModal(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={isSubmitting}
                        disabledReason={!selectedPropertyId ? 'Please select a property' : undefined}
                    >
                        Assign Slot
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">
                    Select a property to materialize. The system will automatically assign it to the next available slot
                    for its type and start a backfill process.
                </p>

                <div>
                    <LemonLabel>Property to Materialize</LemonLabel>
                    {selectedProperty ? (
                        <LemonButton
                            fullWidth
                            onClick={() => setSelectedPropertyId(null)}
                            sideAction={{
                                icon: <IconX />,
                                tooltip: 'Clear selection',
                                onClick: () => setSelectedPropertyId(null),
                            }}
                        >
                            <span className="flex items-center justify-between gap-2 flex-1">
                                <span>{selectedProperty.name}</span>
                                <LemonTag type="default" size="small">
                                    {selectedProperty.property_type}
                                </LemonTag>
                            </span>
                        </LemonButton>
                    ) : (
                        <div className="deprecated-space-y-2">
                            <LemonInput
                                type="search"
                                placeholder="Search properties..."
                                value={searchTerm}
                                onChange={setSearchTerm}
                                fullWidth
                                autoFocus
                            />
                            <div className="max-h-60 overflow-y-auto">
                                {availablePropertiesLoading ? (
                                    <div className="p-4 text-center text-muted">Loading properties...</div>
                                ) : filteredProperties.length === 0 ? (
                                    <div className="p-4 text-center text-muted">
                                        {searchTerm ? 'No properties match your search' : 'No properties available'}
                                    </div>
                                ) : (
                                    <ul className="deprecated-space-y-px">
                                        {filteredProperties.map((prop: PropertyDefinition) => (
                                            <li key={prop.id}>
                                                <LemonButton
                                                    fullWidth
                                                    role="menuitem"
                                                    size="small"
                                                    onClick={() => {
                                                        setSelectedPropertyId(prop.id)
                                                        setSearchTerm('')
                                                    }}
                                                >
                                                    <span className="flex items-center justify-between gap-2 flex-1">
                                                        <span className="truncate">{prop.name}</span>
                                                        <LemonTag type="default" size="small">
                                                            {prop.property_type}
                                                        </LemonTag>
                                                    </span>
                                                </LemonButton>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {availableProperties.length === 0 && !availablePropertiesLoading && (
                    <div className="bg-warning-highlight text-warning rounded p-3 text-sm">
                        No properties available for materialization. All eligible properties have either been
                        materialized or don't have a property_type set.
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
