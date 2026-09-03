import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { AddWidgetModal } from '@posthog/products-dashboards/frontend/widgets/AddWidgetModal'

import { ButtonTileCardModal } from 'lib/components/Cards/ButtonTileCard/ButtonTileCardModal'
import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardMode, DashboardType, QueryBasedInsightModel } from '~/types'

import { ImageTileModal } from 'products/dashboards/frontend/components/ImageTile/ImageTileModal'
import { getImageOnlyTextCardImage } from 'products/dashboards/frontend/components/ImageTile/imageTileUtils'
import { SubscriptionsModal } from 'products/subscriptions/frontend/components/Subscriptions/SubscriptionsModal'

import { DashboardInsightColorsModal } from './DashboardInsightColorsModal'
import { dashboardLogic } from './dashboardLogic'
import { DashboardTemplateEditor } from './DashboardTemplateEditor'
import { DeleteDashboardModal } from './DeleteDashboardModal'
import { DuplicateDashboardModal } from './DuplicateDashboardModal'

export function DashboardModals({ dashboard }: { dashboard: DashboardType<QueryBasedInsightModel> }): JSX.Element {
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
            <SubscriptionsModal
                isOpen={showSubscriptions}
                closeModal={() => push(urls.dashboard(dashboard.id))}
                dashboard={dashboard}
                isCreating={subscriptionId === 'new'}
                subscriptionId={subscriptionId === 'new' ? null : subscriptionId}
            />
            <SharingModal
                title="Dashboard permissions & sharing"
                isOpen={dashboardMode === DashboardMode.Sharing}
                closeModal={() => push(urls.dashboard(dashboard.id))}
                dashboardId={dashboard.id}
                userAccessLevel={dashboard.user_access_level}
                onSharingEnabledChange={(enabled) => updateDashboardSuccess({ ...dashboard, is_shared: enabled })}
            />
            {canEditDashboard && (
                <>
                    {shouldShowImageTileModal && (
                        <ImageTileModal
                            key={selectedImageTileId ?? 'new'}
                            isOpen={shouldShowImageTileModal}
                            onClose={() => push(urls.dashboard(dashboard.id))}
                            dashboard={dashboard}
                            imageTileId={selectedImageTileId}
                        />
                    )}
                    {!shouldShowImageTileModal && (
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
                    {dashboardWidgetsEnabled && (
                        <AddWidgetModal
                            isOpen={addWidgetModalOpen}
                            onClose={() => setAddWidgetModalOpen(false)}
                            loading={addWidgetTileLoading}
                            onAdd={async (widgets) => {
                                await addWidgetTiles({
                                    dashboardId: dashboard.id,
                                    widgets,
                                })
                            }}
                        />
                    )}
                    <DeleteDashboardModal />
                    <DuplicateDashboardModal />
                    <DashboardInsightColorsModal />
                </>
            )}
            {user?.is_staff && <DashboardTemplateEditor />}
            <TerraformExportModal
                isOpen={terraformModalOpen}
                onClose={() => setTerraformModalOpen(false)}
                resource={{ type: 'dashboard', data: dashboard }}
            />
        </>
    )
}
