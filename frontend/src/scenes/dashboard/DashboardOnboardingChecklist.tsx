import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell, IconCheckCircle, IconPlus, IconShare, IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscription } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'
import { dashboardOnboardingChecklistLogic } from './dashboardOnboardingChecklistLogic'

type ChecklistTaskProps = {
    complete: boolean
    description: string
    icon: JSX.Element
    action: JSX.Element
}

function ChecklistTask({ complete, description, icon, action }: ChecklistTaskProps): JSX.Element {
    return (
        <div className="flex gap-3 items-center">
            {complete ? (
                <IconCheckCircle className="text-success shrink-0" />
            ) : (
                <span className="text-muted-alt">{icon}</span>
            )}
            <div className="min-w-0 flex-1 text-sm">{description}</div>
            {action}
        </div>
    )
}

export function DashboardOnboardingChecklist({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { active } = useValues(dashboardOnboardingChecklistLogic({ dashboardId }))

    if (!active) {
        return null
    }

    return <DashboardOnboardingChecklistContent dashboardId={dashboardId} />
}

function DashboardOnboardingChecklistContent({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { dashboard, tiles } = useValues(dashboardLogic)
    const { subscriptions, subscriptionsLoading } = useValues(subscriptionsLogic({ dashboardId }))
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { reportDashboardOnboardingAiStarted } = useActions(eventUsageLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { push } = useActions(router)

    const hasTiles = tiles.length > 0
    const hasSubscription = !subscriptionsLoading && subscriptions.length > 0
    const aiDisabledReason =
        !dataProcessingAccepted &&
        (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')
    const addInsight = (): void => {
        showAddInsightToDashboardModal()
    }
    const askAi = (): void => {
        reportDashboardOnboardingAiStarted(dashboardId, 'checklist')
        openSidePanel(SidePanelTab.Max, '!Help me create a useful first insight for this dashboard.')
    }

    return (
        <div className="px-2 pb-4" data-attr="dashboard-onboarding-checklist">
            <div className="flex flex-col gap-3">
                <ChecklistTask
                    complete={hasTiles}
                    icon={<IconPlus />}
                    description="Add a chart or tile"
                    action={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={addInsight}
                            data-attr="dashboard-onboarding-add-insight"
                        >
                            Add insight
                        </LemonButton>
                    }
                />
                <ChecklistTask
                    complete={hasSubscription}
                    icon={<IconBell />}
                    description="Subscribe to dashboard updates"
                    action={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconBell />}
                            disabledReason={hasTiles ? undefined : 'Add an insight before you create a subscription'}
                            onClick={() => push(urlForSubscription('new', { dashboardId }))}
                            data-attr="dashboard-onboarding-subscribe"
                        >
                            Subscribe
                        </LemonButton>
                    }
                />
                <ChecklistTask
                    complete={!!dashboard?.is_shared}
                    icon={<IconShare />}
                    description="Share this dashboard"
                    action={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconShare />}
                            disabledReason={hasTiles ? undefined : 'Add an insight before you share this dashboard'}
                            onClick={() => push(urls.dashboardSharing(dashboardId))}
                            data-attr="dashboard-onboarding-share"
                        >
                            Share dashboard
                        </LemonButton>
                    }
                />
                <ChecklistTask
                    complete={false}
                    icon={<IconSparkles />}
                    description="Optional: ask PostHog AI for an insight"
                    action={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconSparkles />}
                            disabledReason={aiDisabledReason || undefined}
                            onClick={askAi}
                            data-attr="dashboard-onboarding-ai"
                        >
                            Ask PostHog AI
                        </LemonButton>
                    }
                />
            </div>
        </div>
    )
}
