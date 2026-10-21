import { forwardRef } from 'react'

import { IconTarget } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonBadge } from 'lib/lemon-ui/LemonBadge'

import { ProductSetupPopover } from './ProductSetupPopover'
import { useProductSetupButton } from './useProductSetupButton'

/**
 * ProductSetupButton - A button that appears in the scene title section
 * and allows users to access quick start guides for any product.
 * The selected product is managed by globalSetupLogic, with auto-selection
 * handled by SceneContent when a productKey is provided.
 */
export function ProductSetupButton(): JSX.Element | null {
    const {
        shouldShowButton,
        selectedProduct,
        isOpen,
        isDismissed,
        remainingCount,
        shouldShowSetup,
        showPulse,
        toggle,
        close,
        setSelectedProduct,
    } = useProductSetupButton()

    if (!shouldShowButton) {
        return null
    }

    return (
        <ProductSetupPopover
            visible={isOpen}
            onClickOutside={close}
            selectedProduct={selectedProduct}
            onSelectProduct={setSelectedProduct}
        >
            {isDismissed && !isOpen ? (
                <MinimizedButton remainingCount={remainingCount} isActive={isOpen} onClick={toggle} />
            ) : (
                <ExpandedButton
                    remainingCount={remainingCount}
                    showBadge={shouldShowSetup}
                    isActive={isOpen}
                    onClick={toggle}
                    showPulse={showPulse}
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
                        <LemonBadge.Number count={remainingCount} status="warning" size="medium" position="top-right" />
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
    showPulse: boolean
}

const ExpandedButton = forwardRef<HTMLButtonElement, ExpandedButtonProps>(function ExpandedButton(
    { remainingCount, showBadge, isActive, onClick, showPulse },
    ref
) {
    // Hide the pulse when the popover is open to avoid distracting the user, but keep the
    // numeric badge visible in the control variant so its behavior matches the pre-experiment baseline.
    const showIndicator = showBadge && remainingCount > 0 && (!showPulse || !isActive)

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
                showIndicator ? (
                    showPulse ? (
                        <span className="relative flex h-3 w-3">
                            <span className="absolute inline-flex h-full w-full rounded-full bg-danger animate-ping opacity-75" />
                            <span className="relative inline-flex h-3 w-3 rounded-full bg-danger" />
                        </span>
                    ) : (
                        <LemonBadge.Number count={remainingCount} status="warning" size="small" />
                    )
                ) : undefined
            }
        >
            Quick start
        </LemonButton>
    )
})
