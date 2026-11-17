import { useActions, useValues } from 'kea'

import { IconCheck, IconEye, IconPause, IconPencil, IconPlay, IconRocket, IconTrash, IconX } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ProductTour, ProgressStatus } from '~/types'

import { productTourDialogHandlers } from './productTourDialogHandlers'
import { productTourLogic } from './productTourLogic'
import { getProductTourStatus, isProductTourRunning, productToursLogic } from './productToursLogic'

const RESOURCE_TYPE = 'product_tour'

interface ProductTourSceneMenuBarProps {
    id: string
    productTour: ProductTour
    /** The edit form gets only its editor actions. */
    editing?: boolean
}

export function ProductTourSceneMenuBar({ editing, ...props }: ProductTourSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!enabled) {
        return null
    }
    return editing ? <ProductTourEditSceneMenuBarInner id={props.id} /> : <ProductTourSceneMenuBarInner {...props} />
}

function ProductTourEditSceneMenuBarInner({ id }: { id: string }): JSX.Element {
    const { draftActionInProgress, isProductTourFormSubmitting } = useValues(productTourLogic({ id }))
    const { discardDraft, submitProductTourForm, openToolbarModal } = useActions(productTourLogic({ id }))

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: 'Save',
            icon: <IconCheck />,
            disabledReason: draftActionInProgress ? 'Saving...' : undefined,
            onSelect: submitProductTourForm,
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Button
                        variant="primary"
                        onClick={submitProductTourForm}
                        loading={isProductTourFormSubmitting}
                        disabledReason={draftActionInProgress ? 'Saving...' : undefined}
                    >
                        Save
                    </Button>
                ),
            },
        },
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            disabledReason: draftActionInProgress ? 'Discarding draft...' : undefined,
            onSelect: discardDraft,
            pinned: {
                order: 2,
                variant: 'secondary',
                render: () => (
                    <Button
                        variant="outline"
                        onClick={discardDraft}
                        loading={draftActionInProgress === 'discard'}
                        disabledReason={draftActionInProgress ? 'Discarding draft...' : undefined}
                    >
                        Cancel
                    </Button>
                ),
            },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-preview`,
            label: 'Preview',
            icon: <IconEye />,
            opensFloatingUi: true,
            onSelect: () => openToolbarModal('preview'),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

function ProductTourSceneMenuBarInner({ id, productTour }: ProductTourSceneMenuBarProps): JSX.Element {
    const { launchValidationIssues } = useValues(productTourLogic({ id }))
    const { editingProductTour, launchProductTour, stopProductTour, resumeProductTour, openToolbarModal } = useActions(
        productTourLogic({ id })
    )
    const { deleteProductTour } = useActions(productToursLogic)
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

    const { handleLaunch, handleStop, handleResume } = productTourDialogHandlers({
        launchValidationIssues,
        editingProductTour,
        launchProductTour,
        stopProductTour,
        resumeProductTour,
    })
    const status = getProductTourStatus(productTour)
    const isRunning = isProductTourRunning(productTour)
    const canResume = status === ProgressStatus.Complete && !productTour.archived

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Delete this product tour?',
            content: (
                <div className="text-sm text-secondary">
                    This action cannot be undone. All tour data will be permanently removed.
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                onClick: () => deleteProductTour(id),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const actions: SceneAction[] = [
        ...fileActions,
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-delete`,
            label: 'Delete product tour',
            icon: <IconTrash />,
            destructive: true,
            opensFloatingUi: true,
            onSelect: confirmDelete,
        },
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-edit-tour`,
            label: 'Edit',
            icon: <IconPencil />,
            onSelect: () => editingProductTour(true),
            pinned: { order: 2, variant: 'secondary' },
        },
        ...(status === ProgressStatus.Draft
            ? ([
                  {
                      group: 'edit',
                      section: 'status',
                      id: `${RESOURCE_TYPE}-menubar-launch`,
                      label: 'Launch',
                      icon: <IconRocket />,
                      onSelect: handleLaunch,
                      pinned: { order: 4, variant: 'primary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isRunning
            ? ([
                  {
                      group: 'edit',
                      section: 'status',
                      id: `${RESOURCE_TYPE}-menubar-stop`,
                      label: 'Stop',
                      icon: <IconPause />,
                      onSelect: handleStop,
                      pinned: {
                          order: 3,
                          variant: 'secondary',
                          render: () => (
                              <Button variant="destructive-outline" onClick={handleStop}>
                                  Stop
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canResume
            ? ([
                  {
                      group: 'edit',
                      section: 'status',
                      id: `${RESOURCE_TYPE}-menubar-resume`,
                      label: 'Resume',
                      icon: <IconPlay />,
                      onSelect: handleResume,
                      pinned: { order: 3, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-preview`,
            label: 'Preview',
            icon: <IconEye />,
            opensFloatingUi: true,
            onSelect: () => openToolbarModal('preview'),
            // Stop or Resume takes the second secondary slot when the tour has one.
            pinned: isRunning || canResume ? undefined : { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
