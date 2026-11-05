import { IconTarget } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { ProductSetupPopover } from 'lib/components/ProductSetup'
import { useProductSetupButton } from 'lib/components/ProductSetup/useProductSetupButton'

export function TodayTopBarQuickStartButton(): JSX.Element | null {
    const {
        shouldShowButton,
        selectedProduct,
        isOpen,
        isDismissed,
        remainingCount,
        toggle,
        close,
        setSelectedProduct,
    } = useProductSetupButton()

    if (!shouldShowButton) {
        return null
    }

    const hasTasksLeft = remainingCount > 0
    const tasksLeft = `${remainingCount} ${remainingCount === 1 ? 'task' : 'tasks'} left`

    return (
        <ProductSetupPopover
            visible={isOpen}
            onClickOutside={close}
            selectedProduct={selectedProduct}
            onSelectProduct={setSelectedProduct}
        >
            <Button
                variant="outline"
                size="icon"
                indicator={hasTasksLeft ? 'default' : undefined}
                aria-label={hasTasksLeft ? `Quick start, ${tasksLeft}` : 'Quick start'}
                aria-pressed={isOpen}
                // The menu covers the tooltip, so the tooltip stays off while the menu is open.
                tooltip={
                    isOpen ? null : (
                        <div className="flex flex-col gap-0.5">
                            <span className="font-medium">Quick start</span>
                            <span>A checklist of tasks to set up PostHog.</span>
                            {hasTasksLeft && <span>{tasksLeft}</span>}
                        </div>
                    )
                }
                className="shrink-0 [--quill-button-indicator-ring:var(--chrome)] aria-pressed:bg-[var(--fill-selected)]"
                onClick={toggle}
                // pinned: autocapture data-attr shared with the title-row trigger
                data-attr={
                    isDismissed && !isOpen ? 'global-product-setup-button-minimized' : 'global-product-setup-button'
                }
            >
                <IconTarget />
            </Button>
        </ProductSetupPopover>
    )
}
