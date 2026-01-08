import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { Error404 } from '~/layout/Error404'

import { ProductTourEdit } from './ProductTourEdit'
import { ProductTourView } from './ProductTourView'
import { ProductTourLogicProps, productTourLogic } from './productTourLogic'

export const scene: SceneExport<ProductTourLogicProps> = {
    component: ProductTourComponent,
    logic: productTourLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ProductTourComponent({ id }: ProductTourLogicProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { productTourMissing, isEditingProductTour } = useValues(productTourLogic({ id }))
    const { editingProductTour } = useActions(productTourLogic({ id }))

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
                </BindLogic>
            )}
        </div>
    )
}

export default ProductTourComponent
