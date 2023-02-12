import { LemonButton } from '@posthog/lemon-ui'
import { IconBranch, IconClipboardEdit, IconEdit, IconLink, IconTextSize } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { ElementType } from '~/types'
import { getShadowRootPopoverContainer } from '../utils'
import { SelectorEditingModal } from '~/toolbar/elements/SelectorEditingModal'
import { posthog } from '~/toolbar/posthog'

function SelectorString({
    value,
    activeElementChain,
}: {
    value: string
    activeElementChain: ElementType[]
}): JSX.Element {
    const [modalOpen, setModalOpen] = useState(false)

    const [last, ...rest] = value.split(' ').reverse()
    const selector = (
        <span>
            {rest.reverse().join(' ')} <strong>{last}</strong>
        </span>
    )

    return (
        <>
            <SelectorEditingModal isOpen={modalOpen} setIsOpen={setModalOpen} activeElementChain={activeElementChain} />
            <div className="flex flex-row items-center">
                {selector}
                <LemonButton
                    icon={<IconEdit />}
                    onClick={() => {
                        posthog.capture('toolbar_manual_selector_modal_opened', { autoDetectedSelector: value })
                        setModalOpen(true)
                    }}
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
