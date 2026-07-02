import { useActions, useValues } from 'kea'

import { IconBell, IconCheck, IconEllipsis, IconRefresh, IconSparkles, IconSupport } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { HealthIssueList } from './components/HealthIssueList'
import { HealthIssueSummaryCards } from './components/HealthIssueSummaryCards'
import { PlatformStatusBanner } from './components/PlatformStatusBanner'
import { healthSceneLogic } from './healthSceneLogic'
import { buildHealthOverviewPrompt, HEALTH_OVERVIEW_QUESTIONS } from './healthUtils'

export const HealthScene = (): JSX.Element => {
    const { showDismissed, healthIssuesLoading, isRefreshInFlight, nextRefreshAvailableAt, issues } =
        useValues(healthSceneLogic)
    const { refreshHealthData, setShowDismissed } = useActions(healthSceneLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const askAiEnabled = !!featureFlags[FEATURE_FLAGS.HEALTH_ASK_AI]

    const now = Date.now()
    const inCooldown = nextRefreshAvailableAt !== null && nextRefreshAvailableAt > now
    const cooldownLabel = inCooldown
        ? `Refresh available in ${humanFriendlyDuration(Math.ceil((nextRefreshAvailableAt! - now) / 1000), {
              maxUnits: 2,
          })}`
        : undefined
    const refreshTooltip = isRefreshInFlight
        ? 'Refreshing health checks...'
        : (cooldownLabel ?? 'Re-run all health checks for this project')

    return (
        <SceneContent>
            <SceneTitleSection name="Health" description={null} resourceType={{ type: 'health' }} />

            <div className="flex items-center justify-between -mt-2 mb-2">
                <p className="text-sm mb-0">See an at-a-glance view of the health of your project.</p>
                <div className="flex items-center gap-1">
                    <LemonButton
                        icon={<IconBell />}
                        type="secondary"
                        size="small"
                        to={urls.healthAlerts()}
                        tooltip="Subscribe to alerts when any health check fires"
                    >
                        Alerts
                    </LemonButton>

                    {askAiEnabled && (
                        <LemonMenu
                            items={HEALTH_OVERVIEW_QUESTIONS.map((question) => ({
                                label: question,
                                onClick: () =>
                                    openSidePanel(SidePanelTab.Max, `!${buildHealthOverviewPrompt(issues, question)}`),
                            }))}
                            placement="bottom-end"
                        >
                            <LemonButton
                                icon={<IconSparkles />}
                                type="secondary"
                                size="small"
                                tooltip="Ask PostHog AI about your health issues"
                            >
                                Ask PostHog AI
                            </LemonButton>
                        </LemonMenu>
                    )}
                    <LemonButton
                        icon={<IconSupport />}
                        type="secondary"
                        size="small"
                        onClick={() => openSupportForm({ kind: 'support', target_area: 'health_overview' })}
                    >
                        Get help from our team
                    </LemonButton>
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="small"
                        tooltip={refreshTooltip}
                        loading={isRefreshInFlight || healthIssuesLoading}
                        disabledReason={cooldownLabel}
                        onClick={() => refreshHealthData()}
                    />
                    <LemonMenu
                        items={[
                            {
                                label: 'Show dismissed',
                                icon: showDismissed ? <IconCheck /> : undefined,
                                onClick: () => setShowDismissed(!showDismissed),
                            },
                        ]}
                        placement="bottom-end"
                    >
                        <LemonButton icon={<IconEllipsis />} type="tertiary" size="small" />
                    </LemonMenu>
                </div>
            </div>

            <div className="flex flex-col gap-6">
                <LemonBanner
                    type="info"
                    className="mb-2"
                    dismissKey="unified-health-page-feedback-banner"
                    action={{ children: 'Send feedback', id: 'unified-health-page-feedback-button' }}
                >
                    We'd love your feedback on the new Health page. Let us know what's working and what could be better!
                </LemonBanner>
                <PlatformStatusBanner />
                <HealthIssueSummaryCards />
                <HealthIssueList />
            </div>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: HealthScene,
    logic: healthSceneLogic,
}
