import { useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { ToolbarUserIntent } from '~/types'

type ToolbarButtonMode = 'edit' | 'preview'

interface ToolbarButtonProps {
    tourId: string
    mode?: ToolbarButtonMode
    type?: 'primary' | 'secondary' | 'tertiary'
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}

const MODE_CONFIG: Record<
    ToolbarButtonMode,
    { label: string; title: string; description: string; intent: ToolbarUserIntent }
> = {
    edit: {
        label: 'Edit in toolbar',
        title: 'Edit product tour in toolbar',
        description: 'Select a URL to launch the toolbar and edit your product tour',
        intent: 'edit-product-tour',
    },
    preview: {
        label: 'Preview in toolbar',
        title: 'Preview product tour',
        description: 'Select a URL to launch the toolbar and preview your product tour on your site',
        intent: 'preview-product-tour',
    },
}

export function ProductToursToolbarButton({
    tourId,
    mode = 'edit',
    type = 'secondary',
    size = 'small',
}: ToolbarButtonProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const config = MODE_CONFIG[mode]

    return (
        <>
            <LemonButton size={size} type={type} onClick={() => setIsModalOpen(true)}>
                {config.label}
            </LemonButton>
            <LemonModal
                title={config.title}
                description={config.description}
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                width={600}
            >
                <div className="mt-4">
                    <AuthorizedUrlList
                        type={AuthorizedUrlListType.TOOLBAR_URLS}
                        addText="Add authorized URL"
                        productTourId={tourId}
                        userIntent={config.intent}
                    />
                </div>
            </LemonModal>
        </>
    )
}
