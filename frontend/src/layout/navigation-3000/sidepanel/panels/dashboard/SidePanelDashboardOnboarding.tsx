import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardOnboardingChecklist } from 'scenes/dashboard/DashboardOnboardingChecklist'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'

export function SidePanelDashboardOnboarding(): JSX.Element {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { location } = useValues(router)
    const dashboardIdMatch = location.pathname.match(/\/dashboard\/(\d+)/)
    const dashboardId = Number(selectedTabOptions || dashboardIdMatch?.[1])

    return (
        <SidePanelContentContainer>
            <SidePanelPaneHeader title="Onboarding checklist" />
            {Number.isFinite(dashboardId) && dashboardId > 0 && (
                <BindLogic logic={dashboardLogic} props={{ id: dashboardId }}>
                    <DashboardOnboardingChecklist dashboardId={dashboardId} />
                </BindLogic>
            )}
        </SidePanelContentContainer>
    )
}
