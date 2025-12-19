import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ProductToursTable } from './components/ProductToursTable'
import { ProductToursTabs, productToursLogic } from './productToursLogic'

export const scene: SceneExport = {
    component: ProductTours,
    logic: productToursLogic,
}

function NewTourButton(): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)

    return (
        <>
            <LemonButton size="small" type="primary" onClick={() => setIsModalOpen(true)} data-attr="new-product-tour">
                New tour
            </LemonButton>
            <LemonModal
                title="Create a new product tour"
                description="Select a URL to launch the toolbar and create your product tour"
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                width={600}
            >
                <div className="mt-4">
                    <AuthorizedUrlList
                        type={AuthorizedUrlListType.TOOLBAR_URLS}
                        addText="Add authorized URL"
                        productTourId="new"
                    />
                </div>
            </LemonModal>
        </>
    )
}

function ProductTours(): JSX.Element {
    const { tab } = useValues(productToursLogic)
    const { setTab } = useActions(productToursLogic)

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
