import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCloud, IconTerminal } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { useWizardCommand } from '../useWizardCommand'
import { activeCloudRunLogic, CloudRunHandle } from './activeCloudRunLogic'
import { installationProgressLogic } from './installationProgressLogic'
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
    /**
     * Force the cloud arm off regardless of the experiment flag. The self-driving flow runs a
     * program the cloud runner cannot execute (it rejects `--ci` and needs an interactive terminal),
     * so offering it there would queue a run that can never succeed.
     */
    offerCloudRun?: boolean
}

// Phases InstallationProgressContent already treats as settled — it renders the dismiss control and
// (on error) its own "Run it yourself" button for these. The segmented control's local tab must agree:
// blocking it past these phases strands the user on a dead run with no visible way out.
const SETTLED_INSTALLATION_PHASES = new Set(['completed', 'error', 'idle'])

/**
 * Reads whether the held cloud run has settled (completed, errored, or gone quiet) so the local tab
 * can unblock the moment it does, rather than waiting on `activeCloudRunLogic`'s handle to clear (an
 * explicit dismiss, or its up-to-a-minute reconcile). Only ever rendered while a handle exists — that
 * gate matters, not just as an optimization: `installationProgressLogic` unconditionally opens the
 * wizard-session stream on mount, so mounting it for every install-step visit, active run or not,
 * would open a stream nothing needs (see WizardSyncFab, which gates the same logic behind a live
 * handle for the same reason).
 */
function CloudRunSettledGate({
    handle,
    children,
}: {
    handle: CloudRunHandle
    children: (settled: boolean) => JSX.Element
}): JSX.Element {
    const { installationProgress } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: handle.runId, taskId: handle.taskId })
    )
    return children(SETTLED_INSTALLATION_PHASES.has(installationProgress.phase))
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
    offerCloudRun = true,
}: WizardInstallOptionsProps): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)
    const [mode, setMode] = useState<WizardInstallMode>('cloud')

    const offerCloud = offerCloudRun && cloudRunEnabled && isCloudOrDev

    // A failed (or cancelled) cloud run's fallback: drop the dead run (unblocks local, clears its FAB)
    // and switch to the command.
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

    const renderOptions = (localBlocked: boolean): JSX.Element => {
        // GROW-95: once a cloud run is spawned you cannot also run it locally, so the local tab is
        // blocked and the view pins to the cloud run's progress while `localBlocked` holds.
        const effectiveMode: WizardInstallMode = localBlocked ? 'cloud' : mode

        // Switching to the local tab always means abandoning whatever cloud run is on record, settled
        // or not — otherwise the handle (and its FAB) lingers after the view has already moved on.
        const selectMode = (value: WizardInstallMode): void => {
            if (value === 'local' && activeCloudRun) {
                runItYourself()
            } else {
                setMode(value)
            }
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
                        selectMode(value)
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

    if (activeCloudRun) {
        return <CloudRunSettledGate handle={activeCloudRun}>{(settled) => renderOptions(!settled)}</CloudRunSettledGate>
    }
    return renderOptions(false)
}
