import { getShadowRootPopoverContainer } from '~/toolbar/utils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useState } from 'react'
import { ElementType } from '~/types'

export const SelectorEditingModal = ({
    isOpen,
    setIsOpen,
    activeElementChain,
    onChange,
    startingSelector,
}: {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
    activeElementChain: ElementType[]
    onChange?: (selector: string | null) => void
    startingSelector?: string | null
}): JSX.Element => {
    const [chosenSelector, setChosenSelector] = useState<string | null>(null)

    return (
        <LemonModal
            forceAbovePopovers={true}
            getPopupContainer={getShadowRootPopoverContainer}
            description="Click on elements and their attributes to build a selector"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={(e) => {
                            e.stopPropagation()
                            console.log('calling onChange from modal with ', chosenSelector)
                            onChange?.(chosenSelector)
                            setIsOpen(false)
                        }}
                    >
                        Apply
                    </LemonButton>
                </>
            }
            onClose={() => setIsOpen(false)}
            isOpen={isOpen}
            title="Edit the selector"
        >
            <HTMLElementsDisplay
                editable={true}
                highlight={false}
                elements={activeElementChain}
                checkUniqueness={true}
                onChange={setChosenSelector}
                startingSelector={startingSelector ?? undefined}
            />
        </LemonModal>
    )
}
