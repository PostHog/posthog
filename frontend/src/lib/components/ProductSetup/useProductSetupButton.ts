import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { globalSetupLogic } from './globalSetupLogic'
import { productSetupLogic } from './productSetupLogic'
import type { QuickStartOpenSource, QuickStartSurface } from './types'

export interface ProductSetupButtonState {
    shouldShowButton: boolean
    selectedProduct: ProductKey
    isOpen: boolean
    isDismissed: boolean
    remainingCount: number
    shouldShowSetup: boolean
    showPulse: boolean
    toggle: () => void
    close: () => void
    setSelectedProduct: (product: ProductKey) => void
}

/** The quick start trigger's state and its keyboard shortcut. Mount it once, in whichever trigger is on screen. */
export function useProductSetupButton(surface: QuickStartSurface): ProductSetupButtonState {
    const { selectedProduct, isGlobalModalOpen, sceneHasNoSetup } = useValues(globalSetupLogic)
    const { openGlobalSetup, closeGlobalSetup, setSelectedProduct, reportQuickStartShown } = useActions(globalSetupLogic)
    const { isCurrentOrganizationNew } = useValues(organizationLogic)
    const showPulse = useFeatureFlag('QUICK_START_PULSE_INDICATOR', 'test')

    // Get the setup state for the selected product
    const logic = productSetupLogic({ productKey: selectedProduct })
    const { remainingCount, shouldShowSetup, isDismissed } = useValues(logic)
    const { undismissSetup } = useActions(logic)

    // Show button if there are remaining tasks OR if the modal is currently open (to show completion)
    const shouldShowButton = isCurrentOrganizationNew && !sceneHasNoSetup && (remainingCount > 0 || isGlobalModalOpen)

    const minimized = isDismissed && !isGlobalModalOpen

    useEffect(() => {
        if (shouldShowButton) {
            reportQuickStartShown(selectedProduct, { surface, minimized, remainingCount })
        }
    }, [shouldShowButton, selectedProduct, surface, minimized, remainingCount, reportQuickStartShown])

    const toggle = (source: QuickStartOpenSource): void => {
        if (isGlobalModalOpen) {
            closeGlobalSetup()
        } else {
            if (isDismissed) {
                undismissSetup()
            }
            openGlobalSetup({ source, surface, minimized, remainingCount })
        }
    }

    useShortcut({
        name: 'QuickStartGlobal',
        keybind: [keyBinds.quickStart],
        intent: 'Open quick start guide',
        interaction: 'function',
        callback: () => toggle('shortcut'),
        disabled: !shouldShowButton,
    })

    return {
        shouldShowButton,
        selectedProduct,
        isOpen: isGlobalModalOpen,
        isDismissed,
        remainingCount,
        shouldShowSetup,
        showPulse,
        toggle: () => toggle('button'),
        close: closeGlobalSetup,
        setSelectedProduct,
    }
}
