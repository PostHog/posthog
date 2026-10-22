import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCloud, IconTerminal } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { useWizardCommand } from '../useWizardCommand'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import { WizardCloudRunBlock } from './WizardCloudRunBlock'
import { WizardFrameworkBadges, type WizardShellHog } from './WizardModeShell'

export type WizardInstallMode = 'cloud' | 'local'

export interface WizardInstallOptionsProps {
    /** The local "run it yourself" arm. Callers supply their own command block. */
    localBlock: React.ReactNode
    /** Passed to the cloud run block; `null` keeps the compact onboarding card free of the hedgehog. */
    hog?: WizardShellHog
    /** Called when a cloud run is queued (e.g. advance or unblock the step). */
    onQueued?: () => void
    /** Instrumentation hook, fired when the user switches between cloud and local. */
    onModeSelected?: (mode: WizardInstallMode) => void
    /**
     * Force the cloud arm off regardless of the experiment flag. The cloud runner only executes the
     * base integration program, so offering it for any other program would queue a run that can
     * never succeed.
     */
    offerCloudRun?: boolean
    /**
     * Treat a persisted cloud run as absent. A run queued on another step only executes the base
     * integration program, so a dedicated-program step must keep showing its own command instead
     * of the run's progress.
     */
    ignoreActiveCloudRun?: boolean
    /** Replaces the default framework badge row. */
    badges?: React.ReactNode
}

/**
 * One wizard, two ways to run it: have us run it and open a PR (the cloud run), or run the CLI
 * yourself. A segmented control switches between them. The cloud path only exists behind
 * ONBOARDING_WIZARD_CLOUD_RUN (the AB test arm) on cloud/dev. Elsewhere this collapses to just
 * the caller's local block, so the control arm is unchanged.
 */
export function WizardInstallOptions({
    localBlock,
    hog,
    onQueued,
    onModeSelected,
    offerCloudRun = true,
    ignoreActiveCloudRun = false,
    badges: badgesOverride,
}: WizardInstallOptionsProps): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const { activeCloudRun: persistedCloudRun } = useValues(activeCloudRunLogic)
    const activeCloudRun = ignoreActiveCloudRun ? null : persistedCloudRun
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)
    const [mode, setMode] = useState<WizardInstallMode>('cloud')

    const offerCloud = offerCloudRun && cloudRunEnabled && isCloudOrDev

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

    // The frameworks are the same whichever way the wizard runs, so the badge list rides with the
    // options everywhere. Self-hosted gets no wizard, so no badges either.
    const badges = isCloudOrDev && <div className="pb-2">{badgesOverride ?? <WizardFrameworkBadges />}</div>

    if (!offerCloud) {
        // A persisted run outlives the experiment arm: keep rendering its progress (with the local
        // fallback) even when the flag no longer offers new cloud runs, so nothing is stranded.
        return (
            <div className="flex flex-col gap-4">
                {badges}
                {activeCloudRun ? (
                    <WizardCloudRunBlock hog={hog} onRetryLocally={runItYourself} onQueued={onQueued} />
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
                <WizardCloudRunBlock hog={hog} onRetryLocally={runItYourself} onQueued={onQueued} />
            ) : (
                localBlock
            )}
        </div>
    )
}
