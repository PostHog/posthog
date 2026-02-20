import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ProductTourStatusTag } from './components/ProductToursTable'
import { ProductTourStepsEditor } from './editor'
import { productTourLogic } from './productTourLogic'

export function ProductTourEdit({ id }: { id: string }): JSX.Element {
    const { productTour, productTourForm, isProductTourFormSubmitting, pendingToolbarOpen } = useValues(
        productTourLogic({ id })
    )
    const { editingProductTour, setProductTourFormValue, submitProductTourForm, submitAndOpenToolbar } = useActions(
        productTourLogic({ id })
    )

    if (!productTour) {
        return <LemonSkeleton />
    }

    return (
        <Form logic={productTourLogic} props={{ id }} formKey="productTourForm">
            <SceneContent>
                <SceneTitleSection
                    name={productTourForm.name}
                    resourceType={{ type: 'product_tour' }}
                    canEdit
                    forceEdit
                    onNameChange={(name) => setProductTourFormValue('name', name)}
                    renameDebounceMs={0}
                    forceBackTo={{
                        key: Scene.ProductTour,
                        name: productTour.name,
                        path: urls.productTour(id),
                    }}
                    actions={
                        <div className="flex items-center gap-2">
                            <ProductTourStatusTag tour={productTour} />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => submitAndOpenToolbar('preview')}
                                loading={pendingToolbarOpen}
                            >
                                Preview
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={() => editingProductTour(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => submitProductTourForm()}
                                loading={isProductTourFormSubmitting && !pendingToolbarOpen}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                />

                <div data-attr="product-tours-tour-editor-banner" />
                <ProductTourStepsEditor tourId={id} />
            </SceneContent>
        </Form>
    )
}
