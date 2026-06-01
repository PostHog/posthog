import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBell, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

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
import { SdkSection } from './SdkDoctorComponents'
import { type OutdatedTrafficAlert, type SdkDoctorLoadError, SdkType, sdkDoctorLogic } from './sdkDoctorLogic'
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
        loadError,
        snoozedUntil,
    } = useValues(sdkDoctorLogic)
    const { isDev } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const healthAlertsEnabled = !!featureFlags[FEATURE_FLAGS.HEALTH_ALERTS]

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
                        {healthAlertsEnabled && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={urls.healthAlerts(['sdk_outdated'])}
                                onClick={() => {
                                    posthog.capture('health_alerts_entry_point_clicked', { source: 'sdk_doctor' })
                                }}
                                icon={<IconBell className="size-4" />}
                                tooltip="Subscribe to alerts when SDKs go outdated"
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
                {loading ? (
                    <div className="flex items-center justify-center gap-2 text-muted p-8">
                        <Spinner className="text-lg" />
                        <span>Loading SDK information...</span>
                    </div>
                ) : hasErrors ? (
                    <SdkDoctorErrorState loadError={loadError} onRetry={scanEvents} />
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
        </SceneContent>
    )
}

function SdkDoctorErrorState({
    loadError,
    onRetry,
}: {
    loadError: SdkDoctorLoadError | null
    onRetry: () => void
}): JSX.Element {
    if (loadError?.kind === 'auth') {
        return (
            <LemonBanner type="error">
                <p className="font-semibold">We couldn't load your SDK information.</p>
                <p className="text-sm mt-1">
                    Your session may have expired or you don't have access to this data. Reload the page to sign in
                    again.
                </p>
                <LemonButton
                    className="mt-2"
                    type="primary"
                    icon={<IconRefresh className="size-4" />}
                    onClick={() => window.location.reload()}
                >
                    Reload page
                </LemonButton>
            </LemonBanner>
        )
    }

    const isNetwork = loadError?.kind === 'network'
    return (
        <LemonBanner type="error">
            <p className="font-semibold">We couldn't load your SDK information.</p>
            <p className="text-sm mt-1">
                {isNetwork
                    ? "We couldn't reach PostHog - check your connection and try again."
                    : 'Something went wrong on our end. Try again in a moment.'}
            </p>
            <LemonButton
                className="mt-2"
                type="primary"
                icon={<IconRefresh className="size-4" />}
                onClick={onRetry}
            >
                Try again
            </LemonButton>
        </LemonBanner>
    )
}
