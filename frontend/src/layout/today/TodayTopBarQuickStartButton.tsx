import { IconTarget } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { ProductSetupPopover } from 'lib/components/ProductSetup'
import { useProductSetupButton } from 'lib/components/ProductSetup/useProductSetupButton'

export function TodayTopBarQuickStartButton(): JSX.Element | null {
    const {
        shouldShowButton,
        selectedProduct,
        isOpen,
        isDismissed,
        remainingCount,
        shouldShowSetup,
        toggle,
        close,
        setSelectedProduct,
    } = useProductSetupButton()

    if (!shouldShowButton) {
        return null
    }

    const minimized = isDismissed && !isOpen
    // The count stays while the guide is open, so the trigger does not change shape under the pointer.
    const showCount = (shouldShowSetup || minimized) && remainingCount > 0

    return (
        <ProductSetupPopover
            visible={isOpen}
            onClickOutside={close}
            selectedProduct={selectedProduct}
            onSelectProduct={setSelectedProduct}
        >
            <Button
                variant="outline"
                size={minimized ? 'icon' : 'default'}
                aria-label={minimized ? 'Quick start' : undefined}
                aria-pressed={isOpen}
                className="shrink-0 aria-pressed:bg-[var(--fill-selected)]"
                onClick={toggle}
                // pinned: autocapture data-attr shared with the title-row trigger
                data-attr={minimized ? 'global-product-setup-button-minimized' : 'global-product-setup-button'}
            >
                <IconTarget />
                {!minimized && 'Quick start'}
                {showCount && (
                    <Badge variant="warning" translate="no">
                        {remainingCount}
                    </Badge>
                )}
            </Button>
        </ProductSetupPopover>
    )
}
