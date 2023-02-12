import { getShadowRootPopoverContainer } from '~/toolbar/utils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HtmlElementsDisplay } from 'lib/components/HtmlElementsDisplay/HtmlElementsDisplay'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementType } from '~/types'
import { posthog } from '~/toolbar/posthog'

export const SelectorEditingModal = ({
    isOpen,
    setIsOpen,
    activeElementChain,
}: {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
    activeElementChain: ElementType[]
}): JSX.Element => {
    const { activeMeta } = useValues(elementsLogic)
    const { overrideSelector } = useActions(elementsLogic)

    const [overriddenSelector, setOverriddenSelector] = useState<string | null>(null)
    const [overriddenSelectorIsUnique, setOverriddenSelectorIsUnique] = useState<boolean>(false)

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
                            if (activeMeta !== null) {
                                posthog.capture('toolbar_manual_selector_applied', {
                                    chosenSelector: overriddenSelector,
                                })
                                overrideSelector(activeMeta.element, overriddenSelector)
                                setIsOpen(false)
                            }
                        }}
                        disabled={!overriddenSelectorIsUnique}
                    >
                        Apply
                    </LemonButton>
                </>
            }
            onClose={() => setIsOpen(false)}
            isOpen={isOpen}
            title="Manually override the selector"
        >
            <HtmlElementsDisplay
                editable={true}
                highlight={false}
                elements={activeElementChain}
                checkUniqueness={true}
                onChange={(selector, isUnique) => {
                    if (selector.trim() !== overriddenSelector?.trim()) {
                        posthog.capture('toolbar_manual_selector_changed', { chosenSelector: selector })
                        setOverriddenSelector(selector.trim())
                        setOverriddenSelectorIsUnique(!!isUnique)
                    }
                }}
            />
        </LemonModal>
    )
}
