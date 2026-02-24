import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SdkSection } from '~/layout/navigation-3000/sidepanel/panels/SidePanelSdkDoctor'
import { SdkType, sidePanelSdkDoctorLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSdkDoctorLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

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
    } = useValues(sidePanelSdkDoctorLogic)
    const { isDev } = useValues(preflightLogic)

    const { loadRawData, snoozeSdkDoctor } = useActions(sidePanelSdkDoctorLogic)

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
                        appropriate Dasgter jobs: <LemonTag>cache_all_team_sdk_versions_job</LemonTag> and{' '}
                        <LemonTag>cache_github_sdk_versions_job</LemonTag>. Data won't be available otherwise.
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
                            <p className="font-semibold">
                                An outdated SDK means you're missing out on bug fixes and enhancements.
                            </p>
                            <p className="text-sm mt-1">Check the links below to get caught up.</p>
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
