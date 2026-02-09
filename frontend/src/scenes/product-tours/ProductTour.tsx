import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { Error404 } from '~/layout/Error404'
import { ProductKey } from '~/queries/schema/schema-general'

import { ProductTourEdit } from './ProductTourEdit'
import { ProductTourView } from './ProductTourView'
import { ProductTourLogicProps, productTourLogic } from './productTourLogic'

export const scene: SceneExport<ProductTourLogicProps> = {
    component: ProductTourComponent,
    logic: productTourLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
    productKey: ProductKey.PRODUCT_TOURS,
}

export function ProductTourComponent({ id }: ProductTourLogicProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { productTourMissing, isEditingProductTour, isToolbarModalOpen, toolbarMode } = useValues(
        productTourLogic({ id })
    )
    const { editingProductTour, closeToolbarModal } = useActions(productTourLogic({ id }))

    useEffect(() => {
        return () => {
            editingProductTour(false)
        }
    }, [editingProductTour])

    if (!featureFlags[FEATURE_FLAGS.PRODUCT_TOURS]) {
        return <Error404 />
    }

    if (productTourMissing) {
        return <NotFound object="product tour" />
    }

    return (
        <div>
            {!id ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={productTourLogic} props={{ id }}>
                    {isEditingProductTour ? <ProductTourEdit id={id} /> : <ProductTourView id={id} />}

                    <LemonModal
                        title={toolbarMode === 'edit' ? 'Edit in toolbar' : 'Preview product tour'}
                        description="Select a URL to launch the toolbar"
                        isOpen={isToolbarModalOpen}
                        onClose={closeToolbarModal}
                        width={600}
                    >
                        <div className="mt-4">
                            <AuthorizedUrlList
                                type={AuthorizedUrlListType.TOOLBAR_URLS}
                                addText="Add authorized URL"
                                productTourId={id}
                                userIntent={toolbarMode === 'edit' ? 'edit-product-tour' : 'preview-product-tour'}
                                launchInSameTab
                            />
                        </div>
                    </LemonModal>
                </BindLogic>
            )}
        </div>
    )
}

export default ProductTourComponent
