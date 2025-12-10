import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { productToursLogic } from './productToursLogic'

export function NewTourModal(): JSX.Element | null {
    const { selectedTourId, tourForm, tourSetupCompleted } = useValues(productToursLogic)
    const { setTourFormValue, inspectForElementWithIndex, selectTour } = useActions(productToursLogic)
    const [tourName, setTourName] = useState('')

    // Only show for new tours that haven't completed the initial setup
    const shouldShowModal = selectedTourId === 'new' && (tourForm?.steps?.length ?? 0) === 0 && !tourSetupCompleted

    // Reset the name field when opening a new tour modal
    useEffect(() => {
        if (shouldShowModal) {
            setTourName('')
        }
    }, [shouldShowModal])

    const handleCreateFirstStep = (): void => {
        setTourFormValue('name', tourName)
        inspectForElementWithIndex(0)
    }

    return (
        <LemonModal
            isOpen={shouldShowModal}
            onClose={() => selectTour(null)}
            title="Create a product tour"
            description="Guide users through your product"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => selectTour(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleCreateFirstStep}
                        disabledReason={!tourName.trim() ? 'Enter a tour name' : undefined}
                    >
                        Select first element
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <label className="text-sm font-medium">Tour name</label>
                <LemonInput
                    placeholder="e.g. Welcome tour, Feature walkthrough..."
                    value={tourName}
                    onChange={setTourName}
                    autoFocus
                    onPressEnter={tourName.trim() ? handleCreateFirstStep : undefined}
                />
            </div>
        </LemonModal>
    )
}
