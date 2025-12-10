import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductTourEdit } from './ProductTourEdit'
import { ProductTourView } from './ProductTourView'
import { ProductTourLogicProps, productTourLogic } from './productTourLogic'

export const scene: SceneExport<ProductTourLogicProps> = {
    component: ProductTourComponent,
    logic: productTourLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ProductTourComponent({ id }: ProductTourLogicProps): JSX.Element {
    const { productTourMissing, isEditingProductTour } = useValues(productTourLogic({ id }))
    const { editingProductTour } = useActions(productTourLogic({ id }))

    useEffect(() => {
        return () => {
            editingProductTour(false)
        }
    }, [editingProductTour])

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
