import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell, IconCheckCircle, IconPin, IconPlus, IconSparkles, IconX } from '@posthog/icons'

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
    const { tiles, isPinned } = useValues(dashboardLogic)
    const { subscriptions, subscriptionsLoading } = useValues(subscriptionsLogic({ dashboardId }))
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { togglePinned } = useActions(dashboardLogic)
    const { dismiss } = useActions(dashboardOnboardingChecklistLogic({ dashboardId }))
    const { reportDashboardEmptyAiPromptClicked, reportDashboardOnboardingAiStarted } = useActions(eventUsageLogic)
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
        reportDashboardEmptyAiPromptClicked('Ask PostHog AI for an insight', dashboardId)
        reportDashboardOnboardingAiStarted(dashboardId, 'checklist')
        openSidePanel(SidePanelTab.Max, '!Help me create a useful first insight for this dashboard.')
    }

    return (
        <div className="mb-4 rounded border bg-fill-tertiary p-4" data-attr="dashboard-onboarding-checklist">
            <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                    <h2 className="text-base font-semibold m-0">Set up your dashboard</h2>
                    <p className="text-sm text-secondary m-0 mt-1">
                        Add the data and updates you want to check regularly.
                    </p>
                </div>
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconX />}
                    onClick={dismiss}
                    tooltip="Dismiss checklist"
                    aria-label="Dismiss checklist"
                    data-attr="dashboard-onboarding-dismiss"
                />
            </div>
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
                    complete={isPinned}
                    icon={<IconPin />}
                    description="Pin this dashboard"
                    action={
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPin />}
                            onClick={togglePinned}
                            data-attr="dashboard-onboarding-pin"
                        >
                            Pin dashboard
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
