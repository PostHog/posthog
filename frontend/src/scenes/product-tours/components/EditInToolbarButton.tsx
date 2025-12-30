import { useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

interface EditInToolbarButtonProps {
    tourId: string
    type?: 'primary' | 'secondary' | 'tertiary'
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}

export function EditInToolbarButton({
    tourId,
    type = 'secondary',
    size = 'small',
}: EditInToolbarButtonProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)

    return (
        <>
            <LemonButton size={size} type={type} onClick={() => setIsModalOpen(true)}>
                Edit in toolbar
            </LemonButton>
            <LemonModal
                title="Edit product tour in toolbar"
                description="Select a URL to launch the toolbar and edit your product tour"
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                width={600}
            >
                <div className="mt-4">
                    <AuthorizedUrlList
                        type={AuthorizedUrlListType.TOOLBAR_URLS}
                        addText="Add authorized URL"
                        productTourId={tourId}
                    />
                </div>
            </LemonModal>
        </>
    )
}
