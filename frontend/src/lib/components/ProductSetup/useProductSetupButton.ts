import { useActions, useValues } from 'kea'

import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { globalSetupLogic } from './globalSetupLogic'
import { productSetupLogic } from './productSetupLogic'

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
export function useProductSetupButton(): ProductSetupButtonState {
    const { selectedProduct, isGlobalModalOpen, sceneHasNoSetup } = useValues(globalSetupLogic)
    const { openGlobalSetup, closeGlobalSetup, setSelectedProduct } = useActions(globalSetupLogic)
    const { isCurrentOrganizationNew } = useValues(organizationLogic)
    const showPulse = useFeatureFlag('QUICK_START_PULSE_INDICATOR', 'test')

    // Get the setup state for the selected product
    const logic = productSetupLogic({ productKey: selectedProduct })
    const { remainingCount, shouldShowSetup, isDismissed } = useValues(logic)
    const { undismissSetup } = useActions(logic)

    // Show button if there are remaining tasks OR if the modal is currently open (to show completion)
    const shouldShowButton = isCurrentOrganizationNew && !sceneHasNoSetup && (remainingCount > 0 || isGlobalModalOpen)

    const toggle = (): void => {
        if (isGlobalModalOpen) {
            closeGlobalSetup()
        } else {
            if (isDismissed) {
                undismissSetup()
            }
            openGlobalSetup()
        }
    }

    useShortcut({
        name: 'QuickStartGlobal',
        keybind: [keyBinds.quickStart],
        intent: 'Open quick start guide',
        interaction: 'function',
        callback: toggle,
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
        toggle,
        close: closeGlobalSetup,
        setSelectedProduct,
    }
}
