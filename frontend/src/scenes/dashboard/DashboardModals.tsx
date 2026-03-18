import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { TextCardModal } from 'lib/components/Cards/TextCard/TextCardModal'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { DashboardMode, DashboardType, QueryBasedInsightModel } from '~/types'

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
        terraformModalOpen,
    } = useValues(dashboardLogic)
    const { setTerraformModalOpen } = useActions(dashboardLogic)
    const { push } = useActions(router)
    const { user } = useValues(userLogic)

    return (
        <>
            <SubscriptionsModal
                isOpen={showSubscriptions}
                closeModal={() => push(urls.dashboard(dashboard.id))}
                dashboard={dashboard}
                subscriptionId={subscriptionId}
            />
            <SharingModal
                title="Dashboard permissions & sharing"
                isOpen={dashboardMode === DashboardMode.Sharing}
                closeModal={() => push(urls.dashboard(dashboard.id))}
                dashboardId={dashboard.id}
                userAccessLevel={dashboard.user_access_level}
            />
            {canEditDashboard && (
                <>
                    <TextCardModal
                        isOpen={showTextTileModal}
                        onClose={() => push(urls.dashboard(dashboard.id))}
                        dashboard={dashboard}
                        textTileId={textTileId}
                    />
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
