import { useActions, useValues } from 'kea'
import { useState } from 'react'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { PropertyDefinition, materializedColumnsLogic } from './materializedColumnsLogic'

export function CreateSlotModal(): JSX.Element {
    const { selectedTeamId, availableProperties, availablePropertiesLoading } = useValues(materializedColumnsLogic)
    const { setShowCreateModal, loadSlots } = useActions(materializedColumnsLogic)
    const [selectedPropertyId, setSelectedPropertyId] = useState<number | null>(null)
    const [isSubmitting, setIsSubmitting] = useState(false)

    const handleSubmit = async (): Promise<void> => {
        if (!selectedTeamId || !selectedPropertyId) {
            return
        }

        setIsSubmitting(true)
        try {
            await api.create('api/materialized_column_slots/assign_slot/', {
                team_id: selectedTeamId,
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

    const propertiesByType = availableProperties.reduce(
        (acc, prop) => {
            if (!acc[prop.property_type]) {
                acc[prop.property_type] = []
            }
            acc[prop.property_type].push(prop)
            return acc
        },
        {} as Record<string, PropertyDefinition[]>
    )

    return (
        <LemonModal
            isOpen
            onClose={() => setShowCreateModal(false)}
            title="Assign Materialized Column Slot"
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
                    <LemonSelect
                        placeholder="Select a property..."
                        loading={availablePropertiesLoading}
                        value={selectedPropertyId}
                        onChange={setSelectedPropertyId}
                        options={Object.entries(propertiesByType).flatMap(([type, props]) => [
                            {
                                label: type,
                                options: props.map((prop) => ({
                                    label: prop.name,
                                    value: prop.id,
                                })),
                            },
                        ])}
                    />
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
