import { useActions, useValues } from 'kea'
import { useState } from 'react'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { PropertyDefinition, materializedColumnsLogic } from './materializedColumnsLogic'

export interface AssignSlotForm {
    availableProperties: PropertyDefinition[]
    availablePropertiesLoading: boolean
    filteredProperties: PropertyDefinition[]
    selectedProperty: PropertyDefinition | undefined
    selectedPropertyId: number | null
    setSelectedPropertyId: (id: number | null) => void
    searchTerm: string
    setSearchTerm: (searchTerm: string) => void
    isSubmitting: boolean
    handleSubmit: () => Promise<void>
    close: () => void
}

/** The property pick and submit of the "Assign slot" modal, shared by its Lemon and quill versions. */
export function useAssignSlotForm(): AssignSlotForm {
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
            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
            await api.create(`api/projects/${currentTeam.id}/materialized_column_slots/assign_slot/`, {
                property_definition_id: selectedPropertyId,
            })
            lemonToast.success('Property queued for materialization — it will be picked up by the next weekly cycle')
            setShowCreateModal(false)
            loadSlots()
        } catch (error: any) {
            lemonToast.error(error.detail || 'Failed to queue property for materialization')
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

    return {
        availableProperties,
        availablePropertiesLoading,
        filteredProperties,
        selectedProperty,
        selectedPropertyId,
        setSelectedPropertyId,
        searchTerm,
        setSearchTerm,
        isSubmitting,
        handleSubmit,
        close: () => setShowCreateModal(false),
    }
}
