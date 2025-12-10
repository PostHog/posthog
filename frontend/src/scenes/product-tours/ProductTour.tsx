import { BindLogic, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductTourView } from './ProductTourView'
import { ProductTourLogicProps, productTourLogic } from './productTourLogic'

export const scene: SceneExport<ProductTourLogicProps> = {
    component: ProductTourComponent,
    logic: productTourLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function ProductTourComponent({ id }: ProductTourLogicProps): JSX.Element {
    const { productTourMissing } = useValues(productTourLogic({ id }))

    if (productTourMissing) {
        return <NotFound object="product tour" />
    }

    return (
        <div>
            {!id ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={productTourLogic} props={{ id }}>
                    <ProductTourView id={id} />
                </BindLogic>
            )}
        </div>
    )
}

export default ProductTourComponent
