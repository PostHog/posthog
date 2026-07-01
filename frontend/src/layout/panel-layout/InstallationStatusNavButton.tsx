import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/wizardActiveSessionDetectorLogic'
import { activeCloudRunLogic } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/activeCloudRunLogic'
import { installationProgressLogic } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/installationProgressLogic'

import { installationStatusNavLogic, type NavInstallationPhase } from './installationStatusNavLogic'

// 1Hz clock for the elapsed timer, scoped so nothing ticks when no run is active.
function useNow(): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [])
    return now
}

function phaseDotClass(phase: NavInstallationPhase): string {
    switch (phase) {
        case 'completed':
            return 'bg-success'
        case 'error':
            return 'bg-danger'
        case 'idle':
            return 'bg-muted'
        case 'connecting':
        case 'running':
            return 'bg-accent animate-pulse'
    }
}

/**
 * A small running status indicator shown in the sidebar footer, gated behind
 * `ONBOARDING_WIZARD_SIDEBAR`. Surfaces an active wizard run (cloud or local)
 * or, when onboarding is incomplete, a "Complete setup" link.
 *
 * Follows the same icon/menu pattern as NotificationsMenu — adapts to collapsed
 * vs expanded nav via `ButtonPrimitive`'s `iconOnly` / `menuItem` props.
 */
export function InstallationStatusNavButton({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element | null {
    const sidebarEnabled = useFeatureFlag('ONBOARDING_WIZARD_SIDEBAR', 'test')
    const { shouldShow, isRunActive, phase: logicPhase, onboardingUrl } = useValues(installationStatusNavLogic)
    const { openDialog } = useActions(installationStatusNavLogic)

    // The detector must be mounted to run the cheap REST poll that surfaces local sessions.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)

    // For cloud runs, mount the progress logic to get the real phase (completed, error, running).
    // Mounted unconditionally — when no cloud run is active the empty-key logic is a no-op.
    const cloudProgress = useValues(
        installationProgressLogic({
            mode: 'cloud',
            runId: activeCloudRun?.runId ?? '',
            taskId: activeCloudRun?.taskId ?? '',
        })
    ).installationProgress

    // Derive the effective phase: prefer cloud progress when available, fall back to the logic phase.
    const effectivePhase: NavInstallationPhase =
        cloudProgress && cloudProgress.isCurrent ? cloudProgress.phase : logicPhase

    // Elapsed time — only meaningful for cloud runs (we have the kickoff timestamp).
    const now = useNow()
    const startedAt = activeCloudRun?.startedAt ?? null
    const elapsedSeconds = startedAt ? elapsedSecondsFrom(startedAt, now) : 0
    const showElapsed = !!startedAt && isRunActive

    // Pulse when the dot's phase changes (cloud run transitions).
    const [badgePulse, setBadgePulse] = useState(false)
    const prevPhaseRef = useRef(effectivePhase)
    useEffect(() => {
        if (effectivePhase !== prevPhaseRef.current) {
            prevPhaseRef.current = effectivePhase
            setBadgePulse(true)
            const timer = window.setTimeout(() => setBadgePulse(false), 600)
            return () => window.clearTimeout(timer)
        }
    }, [effectivePhase])

    if (!sidebarEnabled || !shouldShow) {
        return null
    }

    const handleClick = (): void => {
        if (isRunActive) {
            // Reopen the WizardSyncFab dialog via the shared UI logic
            openDialog()
        } else {
            window.location.href = onboardingUrl
        }
    }

    const tooltipParts: string[] = []
    if (isRunActive) {
        if (effectivePhase === 'completed') {
            tooltipParts.push('PostHog setup complete')
        } else if (effectivePhase === 'error') {
            tooltipParts.push('Setup encountered an error')
        } else {
            tooltipParts.push('PostHog setup is in progress')
        }
        if (showElapsed) {
            const m = Math.floor(elapsedSeconds / 60)
            const s = Math.floor(elapsedSeconds % 60)
            tooltipParts.push(`${m}:${s.toString().padStart(2, '0')}`)
        }
    } else {
        tooltipParts.push('Finish setting up PostHog')
    }

    const tooltipContent = tooltipParts.join(' · ')
    const statusLabel = isRunActive ? 'Installation status' : 'Complete setup'

    return (
        <ButtonPrimitive
            tooltip={iconOnly ? tooltipContent : undefined}
            tooltipPlacement="right"
            tooltipCloseDelayMs={0}
            iconOnly={iconOnly}
            menuItem={!iconOnly}
            onClick={handleClick}
            className="group"
            data-attr="installation-status-nav-button"
        >
            <span
                className={cn(
                    'flex text-secondary group-hover:text-primary transition-transform duration-300',
                    badgePulse ? 'scale-125' : 'scale-100'
                )}
            >
                <span className={cn('inline-block size-2 rounded-full', phaseDotClass(effectivePhase))} />
            </span>
            {!iconOnly && (
                <>
                    <span className="-ml-[2px]">{statusLabel}</span>
                    {showElapsed && (
                        <span className="ml-auto text-xs text-muted tabular-nums">
                            {Math.floor(elapsedSeconds / 60)}:
                            {Math.floor(elapsedSeconds % 60)
                                .toString()
                                .padStart(2, '0')}
                        </span>
                    )}
                </>
            )}
        </ButtonPrimitive>
    )
}
