import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SDK_TYPE_READABLE_NAME } from './sdkConstants'
import { SdkDoctorAlerting } from './SdkDoctorAlerting'
import { SdkSection } from './SdkDoctorComponents'
import { type OutdatedTrafficAlert, SdkType, sdkDoctorLogic } from './sdkDoctorLogic'
import { sdkDoctorSceneLogic } from './sdkDoctorSceneLogic'

export const scene: SceneExport = {
    component: SdkDoctorScene,
    logic: sdkDoctorSceneLogic,
}

export function SdkDoctorScene(): JSX.Element {
    const {
        augmentedData,
        rawDataLoading: loading,
        needsUpdatingCount,
        hasErrors,
        snoozedUntil,
    } = useValues(sdkDoctorLogic)
    const { isDev } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { alertsModalOpen } = useValues(sdkDoctorSceneLogic)
    const { setAlertsModalOpen, openAlertsModal } = useActions(sdkDoctorSceneLogic)
    const alertsEnabled = !!featureFlags[FEATURE_FLAGS.SDK_DOCTOR_ALERTS]

    const { loadRawData, snoozeSdkDoctor } = useActions(sdkDoctorLogic)

    useOnMountEffect(() => {
        posthog.capture('sdk doctor loaded', { needsUpdatingCount })
    })

    const scanEvents = (): void => {
        posthog.capture('sdk doctor scan events')
        loadRawData({ forceRefresh: true })
    }

    const snoozeWarning = (): void => {
        posthog.capture('sdk doctor snooze warning')
        snoozeSdkDoctor()
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="SDK Doctor"
                description="Monitor and maintain your PostHog SDK integrations by automatically detecting version issues, configuration problems, and implementation patterns across your applications."
                resourceType={{
                    to: undefined,
                    type: 'sdk_doctor',
                }}
                actions={
                    <>
                        {alertsEnabled && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={openAlertsModal}
                                icon={<IconBell className="size-4" />}
                                tooltip="Subscribe to outdated-SDK alerts via Slack, Discord, Teams, or webhook"
                            >
                                Alerts
                            </LemonButton>
                        )}
                        <LemonButton
                            size="small"
                            type="primary"
                            disabledReason={loading ? 'Scan in progress' : undefined}
                            onClick={scanEvents}
                            icon={<IconRefresh className="size-4" />}
                        >
                            {loading ? 'Scanning events...' : 'Scan events'}
                        </LemonButton>
                    </>
                }
            />

            {isDev && !inStorybook() && !inStorybookTestRunner() && (
                <div>
                    <LemonBanner type="info">
                        <strong>DEVELOPMENT WARNING!</strong> When running in development, make sure you've run the
                        Dagster job <LemonTag>cache_github_sdk_versions_job</LemonTag>. Team SDK version data is cached
                        by the Temporal <LemonTag>sdk_outdated</LemonTag> health check.
                    </LemonBanner>
                </div>
            )}

            {/* Beta feedback banner */}
            <LemonBanner type="info">
                <strong>SDK Doctor is in Beta!</strong> Help us improve by sharing your feedback?{' '}
                <Link to="#panel=support%3Asupport%3Asdk%3Alow%3Atrue">Send feedback</Link>
            </LemonBanner>

            <div className="p-3">
                {loading ? null : hasErrors ? (
                    <div className="text-center text-muted p-4">
                        Error loading SDK information. Please try again later.
                    </div>
                ) : Object.keys(augmentedData).length === 0 ? (
                    <div className="text-center text-muted p-4">
                        No SDK information found. Are you sure you have our SDK installed? You can scan events to get
                        started.
                    </div>
                ) : needsUpdatingCount === 0 ? (
                    <section className="mb-2">
                        <h3>SDK health is good</h3>
                        <LemonBanner type="success" hideIcon={false}>
                            <p className="font-semibold">All caught up! Your SDKs are up to date.</p>
                            <p className="text-sm mt-1">You've got the latest. Nice work keeping everything current.</p>
                        </LemonBanner>
                    </section>
                ) : (
                    <section className="mb-2">
                        <h3>Time for an update!</h3>
                        <LemonBanner
                            type="warning"
                            hideIcon={false}
                            action={{
                                children: 'Snooze warning for 30 days',
                                disabledReason: snoozedUntil ? 'Already snoozed' : undefined,
                                onClick: snoozeWarning,
                            }}
                        >
                            {Object.entries(augmentedData).flatMap(([sdkType, sdk]) =>
                                sdk.outdatedTrafficAlerts.map((alert: OutdatedTrafficAlert) => (
                                    <p key={`${sdkType}-${alert.version}`} className="text-sm mb-1">
                                        Version <code className="text-xs font-mono">{alert.version}</code> of the{' '}
                                        {SDK_TYPE_READABLE_NAME[sdkType as SdkType]} SDK has captured more than{' '}
                                        {alert.thresholdPercent}% of events in the last 7 days.
                                    </p>
                                ))
                            )}
                            <p className="font-semibold">
                                An outdated SDK means you're missing out on bug fixes and enhancements.
                            </p>
                            <p className="text-sm mt-1">
                                <Link to="https://posthog.com/docs/sdk-doctor/keeping-sdks-current" target="_blank">
                                    Learn how
                                </Link>{' '}
                                to keep your SDK versions current.
                            </p>
                            <p className="text-sm mt-1">See the 'Releases' and 'Docs' links below for more info.</p>
                        </LemonBanner>
                    </section>
                )}
            </div>

            {Object.keys(augmentedData).map((sdkType) => (
                <SdkSection key={sdkType} sdkType={sdkType as SdkType} />
            ))}

            {alertsEnabled && (
                <LemonModal
                    isOpen={alertsModalOpen}
                    onClose={() => setAlertsModalOpen(false)}
                    title="SDK Doctor alerts"
                    description="Get notified when your team has outdated PostHog SDKs."
                    width="80%"
                >
                    <SdkDoctorAlerting
                        onAlertCreated={(hogFunctionId) => {
                            setAlertsModalOpen(false)
                            if (hogFunctionId) {
                                // Pass returnTo so the HogFunctionScene's "Notifications"
                                // breadcrumb (and back-arrow) sends the user back to SDK Doctor.
                                router.actions.push(urls.hogFunction(hogFunctionId), {
                                    returnTo: urls.sdkDoctor(),
                                })
                            }
                        }}
                    />
                </LemonModal>
            )}
        </SceneContent>
    )
}
