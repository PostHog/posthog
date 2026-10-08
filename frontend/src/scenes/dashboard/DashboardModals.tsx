import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense, useEffect } from 'react'

import { ButtonTileCardModal } from 'lib/components/Cards/ButtonTileCard/ButtonTileCardModal'
import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardMode, DashboardType } from '~/types'

import { ImageTileModal } from 'products/dashboards/frontend/components/ImageTile/ImageTileModal'
import { getImageOnlyTextCardImage } from 'products/dashboards/frontend/components/ImageTile/imageTileUtils'

import { DashboardInsightColorsModal } from './DashboardInsightColorsModal'
import { dashboardLogic } from './dashboardLogic'
import { DashboardModalLoading } from './DashboardModalLoading'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { DeleteDashboardModal } from './DeleteDashboardModal'
import { DuplicateDashboardModal } from './DuplicateDashboardModal'

// These modals carry their own editors and integration setup, which a dashboard needs only once one opens.
const AddWidgetModal = lazyWithRetry(() =>
    import('@posthog/products-dashboards/frontend/widgets/AddWidgetModal').then((m) => ({ default: m.AddWidgetModal }))
)
const SharingModal = lazyWithRetry(() =>
    import('lib/components/Sharing/SharingModal').then((m) => ({ default: m.SharingModal }))
)
const SubscriptionsModal = lazyWithRetry(() =>
    import('products/subscriptions/frontend/components/Subscriptions/SubscriptionsModal').then((m) => ({
        default: m.SubscriptionsModal,
    }))
)
const TerraformExportModal = lazyWithRetry(() =>
    import('lib/components/TerraformExporter/TerraformExportModal').then((m) => ({ default: m.TerraformExportModal }))
)

export function DashboardModals({ dashboard }: { dashboard: DashboardType }): JSX.Element {
    const {
        dashboardMode,
        canEditDashboard,
        showSubscriptions,
        subscriptionId,
        showTextTileModal,
        textTileId,
        showImageTileModal,
        showButtonTileModal,
        buttonTileId,
        terraformModalOpen,
        addWidgetModalOpen,
        dashboardWidgetsEnabled,
        addWidgetTileLoading,
    } = useValues(dashboardLogic)
    const { setTerraformModalOpen, setAddWidgetModalOpen, addWidgetTiles } = useActions(dashboardLogic)
    const { updateDashboardSuccess } = useActions(dashboardsModel)
    const { push } = useActions(router)
    const { user } = useValues(userLogic)
    const isSharingOpen = dashboardMode === DashboardMode.Sharing
    const isAddWidgetOpen = dashboardWidgetsEnabled && addWidgetModalOpen
    // Grace-extended so each modal's exit animation finishes before its lazy subtree unmounts.
    const shouldRenderSubscriptions = useKeepMountedWhileOpen(showSubscriptions)
    const shouldRenderSharing = useKeepMountedWhileOpen(isSharingOpen)
    const shouldRenderAddWidget = useKeepMountedWhileOpen(isAddWidgetOpen)
    const shouldRenderTerraform = useKeepMountedWhileOpen(terraformModalOpen)
    const textRouteTile =
        textTileId !== null ? dashboard.tiles?.find((tile) => tile.id === Number(textTileId)) : undefined
    const isCreatingTextTile = textTileId === null
    const textRouteHasImage =
        !!textRouteTile?.text && !!getImageOnlyTextCardImage(textCardConverter, textRouteTile.text.body)
    const buttonRouteTile =
        buttonTileId !== null ? dashboard.tiles?.find((tile) => tile.id === Number(buttonTileId)) : undefined
    const isCreatingButtonTile = buttonTileId === null
    const selectedImageTileId = textRouteHasImage ? (textRouteTile?.id ?? null) : null
    const shouldShowImageTileModal = showImageTileModal || selectedImageTileId !== null
    const hasMissingRouteTile = (textTileId !== null && !textRouteTile) || (buttonTileId !== null && !buttonRouteTile)

    useEffect(() => {
        if (hasMissingRouteTile) {
            push(urls.dashboard(dashboard.id))
        }
    }, [dashboard.id, hasMissingRouteTile, push])

    return (
        <>
            {shouldRenderSubscriptions ? (
                <Suspense
                    fallback={
                        <DashboardModalLoading
                            isOpen={showSubscriptions}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                        />
                    }
                >
                    <SubscriptionsModal
                        isOpen={showSubscriptions}
                        closeModal={() => push(urls.dashboard(dashboard.id))}
                        dashboard={dashboard}
                        subscriptionId={subscriptionId === 'new' ? undefined : subscriptionId}
                    />
                </Suspense>
            ) : null}
            {shouldRenderSharing ? (
                <Suspense
                    fallback={
                        <DashboardModalLoading
                            isOpen={isSharingOpen}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                        />
                    }
                >
                    <SharingModal
                        title="Dashboard permissions & sharing"
                        isOpen={isSharingOpen}
                        closeModal={() => push(urls.dashboard(dashboard.id))}
                        dashboardId={dashboard.id}
                        userAccessLevel={dashboard.user_access_level}
                        onSharingEnabledChange={(enabled) =>
                            updateDashboardSuccess({ ...dashboard, is_shared: enabled })
                        }
                    />
                </Suspense>
            ) : null}
            {canEditDashboard && (
                <>
                    {shouldShowImageTileModal ? (
                        <ImageTileModal
                            key={selectedImageTileId ?? 'new'}
                            isOpen={shouldShowImageTileModal}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                            dashboard={dashboard}
                            imageTileId={selectedImageTileId}
                        />
                    ) : (
                        <TextCardModal
                            isOpen={showTextTileModal && (isCreatingTextTile || !!textRouteTile?.text)}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                            dashboard={dashboard}
                            textTileId={textTileId}
                        />
                    )}
                    <ButtonTileCardModal
                        isOpen={showButtonTileModal && (isCreatingButtonTile || !!buttonRouteTile?.button_tile)}
                        onClose={() => push(urls.dashboard(dashboard.id))}
                        dashboard={dashboard}
                        buttonTileId={buttonTileId}
                    />
                    {shouldRenderAddWidget ? (
                        <Suspense
                            fallback={
                                <DashboardModalLoading
                                    isOpen={isAddWidgetOpen}
                                    onClose={() => setAddWidgetModalOpen(false)}
                                />
                            }
                        >
                            <AddWidgetModal
                                isOpen={isAddWidgetOpen}
                                onClose={() => setAddWidgetModalOpen(false)}
                                loading={addWidgetTileLoading}
                                onAdd={async (widgets) => {
                                    await addWidgetTiles({
                                        dashboardId: dashboard.id,
                                        widgets,
                                    })
                                }}
                            />
                        </Suspense>
                    ) : null}
                    <DeleteDashboardModal />
                    <DuplicateDashboardModal />
                    <DashboardInsightColorsModal />
                </>
            )}
            {user?.is_staff && <DashboardTemplateEditor />}
            {shouldRenderTerraform ? (
                <Suspense
                    fallback={
                        <DashboardModalLoading
                            isOpen={terraformModalOpen}
                            onClose={() => setTerraformModalOpen(false)}
                        />
                    }
                >
                    <TerraformExportModal
                        isOpen={terraformModalOpen}
                        onClose={() => setTerraformModalOpen(false)}
                        resource={{ type: 'dashboard', data: dashboard }}
                    />
                </Suspense>
            ) : null}
        </>
    )
}
