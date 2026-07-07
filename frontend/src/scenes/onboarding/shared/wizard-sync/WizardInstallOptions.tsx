import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { useEffect } from 'react'

import { IconCloud, IconTerminal } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { useWizardCommand } from '../SetupWizardBanner'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import { WizardCloudRunBlock } from './WizardCloudRunBlock'
import { WizardFrameworkBadges } from './WizardModeShell'

export type WizardInstallMode = 'cloud' | 'local'

export interface WizardInstallOptionsProps {
    /** The local "run it yourself" arm. Variants supply their own command block. */
    localBlock: React.ReactNode
    /** Keeps the compact onboarding card free of the wizard hedgehog. */
    hideHog?: boolean
    /** Called when a cloud run is queued (e.g. advance or unblock the step). */
    onQueued?: () => void
    /** Instrumentation hook, fired when the user switches between cloud and local. */
    onModeSelected?: (mode: WizardInstallMode) => void
}

/**
 * One wizard, two ways to run it: have us run it and open a PR (the cloud run), or run the CLI
 * yourself. A segmented control switches between them. Shared by both onboarding variants; the
 * cloud path only exists behind ONBOARDING_WIZARD_CLOUD_RUN (the AB test arm) on cloud/dev —
 * elsewhere this collapses to just the caller's local block, so the control arm is unchanged.
 */
export function WizardInstallOptions({
    localBlock,
    hideHog = false,
    onQueued,
    onModeSelected,
}: WizardInstallOptionsProps): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)
    const { reportWizardCloudRunExperimentExposed } = useActions(onboardingEventUsageLogic)
    const [mode, setMode] = useState<WizardInstallMode>('cloud')

    const offerCloud = cloudRunEnabled && isCloudOrDev

    // GROW-117: this component is where the cloud-run AB arms diverge — control collapses to the
    // local block, test shows the picker — so showing it on a cloud/dev instance IS the exposure.
    // Both gates resolve asynchronously (preflight for isCloudOrDev, posthog-js for the flags), so
    // fire on readiness rather than once at mount: a mount-time snapshot would drop or mis-bucket
    // exposures for exactly the fresh-signup population the experiment measures. The listener
    // dedupes and skips unenrolled users, so re-fires are safe. Self-hosted never offers cloud
    // runs on either arm, so it stays out of the experiment.
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    useEffect(() => {
        if (isCloudOrDev && receivedFeatureFlags) {
            reportWizardCloudRunExperimentExposed()
        }
    }, [isCloudOrDev, receivedFeatureFlags, reportWizardCloudRunExperimentExposed])
    // GROW-95: once a cloud run is spawned you cannot also run it locally, so the local tab is blocked
    // and the view pins to the cloud run's progress until it is cleared (e.g. via the failure fallback).
    const localBlocked = !!activeCloudRun
    const effectiveMode: WizardInstallMode = localBlocked ? 'cloud' : mode

    // A failed cloud run's fallback: drop the dead run (unblocks local, clears its FAB) and switch to
    // the command.
    const runItYourself = (): void => {
        clearActiveCloudRun()
        setMode('local')
    }

    // The frameworks are the same whichever way (and in whichever variant) the wizard runs, so the
    // badge list rides with the options everywhere. Self-hosted gets no wizard, so no badges either.
    const badges = isCloudOrDev && (
        <div className="pb-2">
            <WizardFrameworkBadges />
        </div>
    )

    if (!offerCloud) {
        // A persisted run outlives the experiment arm: keep rendering its progress (with the local
        // fallback) even when the flag no longer offers new cloud runs, so nothing is stranded.
        return (
            <div className="flex flex-col gap-4">
                {badges}
                {activeCloudRun ? (
                    <WizardCloudRunBlock hideHog={hideHog} onRetryLocally={runItYourself} onQueued={onQueued} />
                ) : (
                    localBlock
                )}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {badges}
            <LemonSegmentedButton
                fullWidth
                value={effectiveMode}
                onChange={(value) => {
                    // LemonSegmentedButton fires onChange on any option click, including the one
                    // already selected — only report actual switches.
                    if (value !== effectiveMode) {
                        onModeSelected?.(value)
                    }
                    setMode(value)
                }}
                options={[
                    {
                        value: 'cloud',
                        label: 'Open a pull request',
                        icon: <IconCloud />,
                        'data-attr': 'wizard-mode-cloud',
                    },
                    {
                        value: 'local',
                        label: 'Run it yourself',
                        icon: <IconTerminal />,
                        disabledReason: localBlocked ? 'A cloud run is in progress.' : undefined,
                        'data-attr': 'wizard-mode-local',
                    },
                ]}
            />
            {effectiveMode === 'cloud' ? (
                <WizardCloudRunBlock hideHog={hideHog} onRetryLocally={runItYourself} onQueued={onQueued} />
            ) : (
                localBlock
            )}
        </div>
    )
}
