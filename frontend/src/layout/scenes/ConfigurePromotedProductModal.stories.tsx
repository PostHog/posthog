import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { PromotedProductTargetKind, promotedProductLogic } from '~/layout/panel-layout/ai-first/promotedProductLogic'

import { ConfigurePromotedProductModal } from './ConfigurePromotedProductModal'

interface StoryArgs {
    /** The target kind pre-selected when the modal opens. */
    kind: PromotedProductTargetKind
    /** Product key (kind === 'product') or URL string (kind === 'url'); ignored for 'ai_chat'. */
    value: string
}

/**
 * The modal renders purely from `promotedProductLogic`'s pending fields, so the stories
 * stage those directly via the same actions the modal's own controls dispatch. This keeps
 * the stories independent of feature-flag / localStorage resolution timing — the modal is
 * not flag-gated, only the nav entry that opens it is.
 */
function StoryRunner({ kind, value }: StoryArgs): JSX.Element | null {
    const [ready, setReady] = useState(false)

    useEffect(() => {
        const unmount = promotedProductLogic.mount()
        promotedProductLogic.actions.setPendingKind(kind)
        if (kind === 'product') {
            promotedProductLogic.actions.setPendingProduct(value)
        } else if (kind === 'url') {
            promotedProductLogic.actions.setPendingUrl(value)
        }
        setReady(true)
        return () => {
            unmount()
            setReady(false)
        }
    }, [kind, value])

    if (!ready) {
        return null
    }

    return <ConfigurePromotedProductModal isOpen={true} onClose={() => undefined} />
}

const meta: Meta<StoryArgs> = {
    title: 'Layout/Configure Promoted Product Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: (args) => <StoryRunner {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ProductSelected: Story = {
    args: { kind: 'product', value: 'session_replay' },
}

export const UrlSelected: Story = {
    args: { kind: 'url', value: '/my-dashboard' },
}

export const AiChatSelected: Story = {
    args: { kind: 'ai_chat', value: '' },
}

export const DefaultProduct: Story = {
    args: { kind: 'product', value: 'product_analytics' },
}
