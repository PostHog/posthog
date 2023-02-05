import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HtmlElementsDisplay } from 'lib/components/HtmlElementsDisplay/HtmlElementsDisplay'
import { IconBranch, IconClipboardEdit, IconEdit, IconLink, IconTextSize } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { ElementType } from '~/types'
import { getShadowRootPopoverContainer } from '../utils'
import { elementsLogic } from './elementsLogic'

function SelectorString({
    value,
    activeElementChain,
}: {
    value: string
    activeElementChain: ElementType[]
}): JSX.Element {
    const { activeMeta } = useValues(elementsLogic)
    const { overrideSelector } = useActions(elementsLogic)

    const [modalOpen, setModalOpen] = useState(false)
    const [overriddenSelector, setOverriddenSelector] = useState<string | null>(null)

    const [last, ...rest] = value.split(' ').reverse()
    const selector = (
        <span>
            {rest.reverse().join(' ')} <strong>{last}</strong>
        </span>
    )

    const modal = (
        <LemonModal
            forceAbovePopovers={true}
            getPopupContainer={getShadowRootPopoverContainer}
            description="Click on elements and their attributes to build a selector"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={(e) => {
                            e.stopPropagation()
                            if (activeMeta !== null) {
                                overrideSelector(activeMeta.element, overriddenSelector)
                                setModalOpen(false)
                            }
                        }}
                    >
                        Apply
                    </LemonButton>
                </>
            }
            onClose={() => setModalOpen(false)}
            isOpen={modalOpen}
            title="Manually override the selector"
        >
            <HtmlElementsDisplay
                editable={true}
                highlight={false}
                elements={activeElementChain}
                checkUniqueness={true}
                onChange={(selector) => {
                    if (selector.trim() !== overriddenSelector?.trim()) {
                        setOverriddenSelector(selector.trim())
                    }
                }}
            />
        </LemonModal>
    )

    return (
        <>
            {modal}
            <div className="flex flex-row items-center">
                {selector}
                <LemonButton
                    icon={<IconEdit />}
                    onClick={() => setModalOpen(true)}
                    aria-label={'Manually choose a selector'}
                    title="Manually choose a selector"
                    getTooltipPopupContainer={getShadowRootPopoverContainer}
                />
            </div>
        </>
    )
}

export function ActionAttribute({
    attribute,
    value,
    activeElementChain,
}: {
    attribute: string
    value?: string
    activeElementChain: ElementType[]
}): JSX.Element {
    const icon =
        attribute === 'text' ? (
            <IconTextSize />
        ) : attribute === 'href' ? (
            <IconLink />
        ) : attribute === 'selector' ? (
            <IconBranch />
        ) : (
            <IconClipboardEdit />
        )

    const text =
        attribute === 'href' ? (
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
        ) : attribute === 'selector' ? (
            value ? (
                <span className="font-mono">
                    <SelectorString value={value} activeElementChain={activeElementChain} />
                </span>
            ) : (
                <span>
                    Could not generate a unique selector for this element. Please instrument it with a unique{' '}
                    <code>id</code> or <code>data-attr</code> attribute.
                </span>
            )
        ) : (
            value
        )

    return (
        <div key={attribute} className="flex flex-row gap-2 justify-between items-center">
            <div className="text-muted text-xl">{icon}</div>
            <div className="grow">{text}</div>
        </div>
    )
}
