import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { Error404 } from '~/layout/Error404'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewProductTourModal } from './components/NewProductTourModal'
import { ProductToursTable } from './components/ProductToursTable'
import { ProductToursTabs, productToursLogic } from './productToursLogic'

export const scene: SceneExport = {
    component: ProductTours,
    logic: productToursLogic,
}

function NewTourButton(): JSX.Element {
    const { createAnnouncement, createBanner } = useActions(productToursLogic)
    const [isModalOpen, setIsModalOpen] = useState(false)

    return (
        <>
            <LemonButton size="small" type="primary" onClick={() => setIsModalOpen(true)} data-attr="new-product-tour">
                New
            </LemonButton>
            <NewProductTourModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onCreateAnnouncement={createAnnouncement}
                onCreateBanner={createBanner}
            />
        </>
    )
}

function ProductTours(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(productToursLogic)
    const { setTab } = useActions(productToursLogic)

    if (!featureFlags[FEATURE_FLAGS.PRODUCT_TOURS]) {
        return <Error404 />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.ProductTours].name}
                description={sceneConfigurations[Scene.ProductTours].description}
                resourceType={{ type: 'product_tour' }}
                actions={<NewTourButton />}
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setTab(newTab as ProductToursTabs)}
                tabs={[
                    { key: ProductToursTabs.Active, label: 'Active' },
                    { key: ProductToursTabs.Archived, label: 'Archived' },
                ]}
                sceneInset={true}
            />
            <ProductToursTable />
        </SceneContent>
    )
}

export default ProductTours
