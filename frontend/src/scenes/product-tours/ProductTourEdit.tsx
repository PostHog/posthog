import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ProductTourStatusTag } from './components/ProductToursTable'
import { ProductTourStepsEditor } from './editor'
import { productTourLogic } from './productTourLogic'

export function ProductTourEdit({ id }: { id: string }): JSX.Element {
    const {
        productTour,
        productTourForm,
        isEditingProductTour,
        draftSaveStatus,
        draftActionInProgress,
        isProductTourFormSubmitting,
    } = useValues(productTourLogic({ id }))
    const { discardDraft, submitProductTourForm, setProductTourFormValue, openToolbarModal } = useActions(
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
                            <ProductTourStatusTag
                                tour={productTour}
                                isEditing={isEditingProductTour}
                                draftSaveStatus={draftSaveStatus}
                            />
                            <LemonButton type="secondary" size="small" onClick={() => openToolbarModal('preview')}>
                                Preview
                            </LemonButton>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.ProductTour}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={productTour.user_access_level}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={discardDraft}
                                    loading={draftActionInProgress === 'discard'}
                                    disabledReason={draftActionInProgress ? 'Discarding draft...' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                            </AccessControlAction>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.ProductTour}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={productTour.user_access_level}
                            >
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={submitProductTourForm}
                                    loading={isProductTourFormSubmitting}
                                    disabledReason={draftActionInProgress ? 'Saving...' : undefined}
                                >
                                    Save
                                </LemonButton>
                            </AccessControlAction>
                        </div>
                    }
                />

                <div data-attr="product-tours-tour-editor-banner" />
                <ProductTourStepsEditor tourId={id} />
            </SceneContent>
        </Form>
    )
}
