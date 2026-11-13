import { useState } from 'react'

import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { ElementType } from '~/types'

import { SelectorCount } from './SelectorCount'

export const SelectorEditingModal = ({
    isOpen,
    setIsOpen,
    activeElementChain,
    onChange,
    startingSelector,
    checkUniqueness = true,
}: {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
    activeElementChain: ElementType[]
    onChange?: (selector: string | null) => void
    startingSelector?: string | null
    /** Pass false where the modal doesn't render in the page whose elements it edits. */
    checkUniqueness?: boolean
}): JSX.Element => {
    const [chosenSelector, setChosenSelector] = useState<string | null>(null)

    return (
        <LemonModal
            forceAbovePopovers={true}
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
                checkUniqueness={checkUniqueness}
                onChange={setChosenSelector}
                startingSelector={startingSelector ?? undefined}
            />
            {!checkUniqueness && chosenSelector ? <SelectorCount selector={chosenSelector} /> : null}
        </LemonModal>
    )
}
