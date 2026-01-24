import { useActions, useValues } from 'kea'
import { forwardRef } from 'react'

import { IconTarget } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { organizationLogic } from 'scenes/organizationLogic'

import { ProductSetupPopover } from './ProductSetupPopover'
import { globalSetupLogic } from './globalSetupLogic'
import { productSetupLogic } from './productSetupLogic'

/**
 * ProductSetupButton - A button that appears in the scene title section
 * and allows users to access quick start guides for any product.
 * The selected product is managed by globalSetupLogic, with auto-selection
 * handled by SceneContent when a productKey is provided.
 */
export function ProductSetupButton(): JSX.Element | null {
    const { selectedProduct, isGlobalModalOpen, sceneHasNoSetup } = useValues(globalSetupLogic)
    const { openGlobalSetup, closeGlobalSetup, setSelectedProduct } = useActions(globalSetupLogic)
    const { isCurrentOrganizationNew } = useValues(organizationLogic)

    // Get the setup state for the selected product
    const logic = productSetupLogic({ productKey: selectedProduct })
    const { remainingCount, shouldShowSetup, isDismissed } = useValues(logic)
    const { undismissSetup } = useActions(logic)

    // Show button if there are remaining tasks OR if the modal is currently open (to show completion)
    const shouldShowButton = isCurrentOrganizationNew && !sceneHasNoSetup && (remainingCount > 0 || isGlobalModalOpen)

    const handleToggle = (): void => {
        if (isGlobalModalOpen) {
            closeGlobalSetup()
        } else {
            if (isDismissed) {
                undismissSetup()
            }
            openGlobalSetup()
        }
    }

    useAppShortcut({
        name: 'QuickStartGlobal',
        keybind: [keyBinds.quickStart],
        intent: 'Open quick start guide',
        interaction: 'function',
        callback: handleToggle,
        disabled: !shouldShowButton,
    })

    if (!shouldShowButton) {
        return null
    }

    return (
        <ProductSetupPopover
            visible={isGlobalModalOpen}
            onClickOutside={closeGlobalSetup}
            selectedProduct={selectedProduct}
            onSelectProduct={setSelectedProduct}
        >
            {isDismissed && !isGlobalModalOpen ? (
                <MinimizedButton remainingCount={remainingCount} isActive={isGlobalModalOpen} onClick={handleToggle} />
            ) : (
                <ExpandedButton
                    remainingCount={remainingCount}
                    showBadge={shouldShowSetup}
                    isActive={isGlobalModalOpen}
                    onClick={handleToggle}
                />
            )}
        </ProductSetupPopover>
    )
}

interface MinimizedButtonProps {
    remainingCount: number
    isActive: boolean
    onClick: () => void
}

const MinimizedButton = forwardRef<HTMLButtonElement, MinimizedButtonProps>(function MinimizedButton(
    { remainingCount, isActive, onClick },
    ref
) {
    return (
        <LemonButton
            ref={ref}
            icon={
                <span className="relative">
                    <IconTarget />
                    {remainingCount > 0 && (
                        <span className="absolute -top-1.5 -right-1.5 flex items-center justify-center w-3.5 h-3.5 text-[9px] font-bold bg-warning text-white rounded-full">
                            {remainingCount}
                        </span>
                    )}
                </span>
            }
            size="small"
            type="secondary"
            onClick={onClick}
            active={isActive}
            tooltip="Quick start (click to expand)"
            data-attr="global-product-setup-button-minimized"
        />
    )
})

interface ExpandedButtonProps {
    remainingCount: number
    showBadge: boolean
    isActive: boolean
    onClick: () => void
}

const ExpandedButton = forwardRef<HTMLButtonElement, ExpandedButtonProps>(function ExpandedButton(
    { remainingCount, showBadge, isActive, onClick },
    ref
) {
    return (
        <LemonButton
            ref={ref}
            icon={<IconTarget />}
            size="small"
            type="secondary"
            onClick={onClick}
            active={isActive}
            data-attr="global-product-setup-button"
            sideIcon={
                showBadge && remainingCount > 0 ? (
                    <span className="flex items-center justify-center min-w-5 h-5 px-1 text-xs font-bold bg-warning text-white rounded-full">
                        {remainingCount}
                    </span>
                ) : undefined
            }
        >
            Quick start
        </LemonButton>
    )
})
