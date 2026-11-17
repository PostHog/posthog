import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { NewProductTourModal } from './components/NewProductTourModal'
import { productToursLogic } from './productToursLogic'

const RESOURCE_TYPE = 'product_tours'

export function ProductToursSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ProductToursSceneMenuBarInner /> : null
}

function ProductToursSceneMenuBarInner(): JSX.Element {
    const { productTours } = useValues(productToursLogic)
    const { createAnnouncement, createBanner, createTour } = useActions(productToursLogic)
    // The title button owns a modal of its own, and pinned actions replace that button, so the menu needs this one.
    const [isModalOpen, setIsModalOpen] = useState(false)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new`,
            label: 'New product tour',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            onSelect: () => setIsModalOpen(true),
            // pinned: data-attr values are wire strings
            pinned: { order: 1, variant: 'primary', dataAttr: 'new-product-tour' },
        },
    ]

    return (
        <>
            <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
            <NewProductTourModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onCreateAnnouncement={createAnnouncement}
                onCreateBanner={createBanner}
                onCreateTour={createTour}
                existingTourNames={new Set(productTours.map((tour) => tour.name).filter(Boolean))}
            />
        </>
    )
}
