import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ProductTourStatusTag } from './components/ProductToursTable'
import { QuillProductTourStatusBadge } from './components/QuillProductTourStatusBadge'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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
                        todayRailNav ? (
                            <div className="flex flex-wrap items-center gap-2">
                                <QuillProductTourStatusBadge
                                    tour={productTour}
                                    isEditing={isEditingProductTour}
                                    draftSaveStatus={draftSaveStatus}
                                />
                                <Button variant="outline" onClick={() => openToolbarModal('preview')}>
                                    Preview
                                </Button>
                                <Button
                                    variant="outline"
                                    onClick={discardDraft}
                                    loading={draftActionInProgress === 'discard'}
                                    disabledReason={draftActionInProgress ? 'Discarding draft...' : undefined}
                                >
                                    Cancel
                                </Button>
                                <Button
                                    variant="primary"
                                    onClick={submitProductTourForm}
                                    loading={isProductTourFormSubmitting}
                                    disabledReason={draftActionInProgress ? 'Saving...' : undefined}
                                >
                                    Save
                                </Button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-2">
                                <ProductTourStatusTag
                                    tour={productTour}
                                    isEditing={isEditingProductTour}
                                    draftSaveStatus={draftSaveStatus}
                                />
                                <LemonButton type="secondary" size="small" onClick={() => openToolbarModal('preview')}>
                                    Preview
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={discardDraft}
                                    loading={draftActionInProgress === 'discard'}
                                    disabledReason={draftActionInProgress ? 'Discarding draft...' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={submitProductTourForm}
                                    loading={isProductTourFormSubmitting}
                                    disabledReason={draftActionInProgress ? 'Saving...' : undefined}
                                >
                                    Save
                                </LemonButton>
                            </div>
                        )
                    }
                />

                <div data-attr="product-tours-tour-editor-banner" />
                <ProductTourStepsEditor tourId={id} />
            </SceneContent>
        </Form>
    )
}
