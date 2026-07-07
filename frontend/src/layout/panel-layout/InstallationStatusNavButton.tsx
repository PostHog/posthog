import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { activeCloudRunLogic, type CloudRunHandle } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { installationProgressLogic } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'

import { installationStatusNavLogic, type NavInstallationPhase } from './installationStatusNavLogic'

// 1Hz clock — only ticks while `enabled` is true (i.e. a run with startedAt is active).
function useNow(enabled: boolean): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        if (!enabled) {
            return
        }
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [enabled])
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
 * Mounts `installationProgressLogic` only when a cloud run is active, and reports the phase
 * back to the parent via a callback. This avoids opening a wizard-session SSE connection for
 * every authenticated user — the logic's `afterMount` calls `connectSession()`, and
 * `wizardSessionStreamLogic` has no empty-workflow guard. Mirrors the `WizardSyncLocalGate` pattern.
 */
function CloudRunPhaseReporter({
    handle,
    onPhase,
}: {
    handle: CloudRunHandle
    onPhase: (phase: NavInstallationPhase | null) => void
}): null {
    const { installationProgress } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: handle.runId, taskId: handle.taskId })
    )
    useEffect(() => {
        onPhase(installationProgress.isCurrent ? installationProgress.phase : null)
    }, [installationProgress, onPhase])
    return null
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
    // Gate BEFORE mounting any logic: the inner component mounts the session detector (directly and
    // via installationStatusNavLogic's connect), whose afterMount starts a 60s REST poll. Flag-off
    // users must not pay that traffic (INC-886 pattern, mirrors WizardProgressFab).
    if (!sidebarEnabled) {
        return null
    }
    return <InstallationStatusNavButtonInner iconOnly={iconOnly} />
}

function InstallationStatusNavButtonInner({ iconOnly }: { iconOnly: boolean }): JSX.Element | null {
    const { shouldShow, isRunActive, phase: logicPhase, onboardingUrl } = useValues(installationStatusNavLogic)
    const { openDialog } = useActions(installationStatusNavLogic)

    // The detector must be mounted to run the cheap REST poll that surfaces local sessions.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)

    // Cloud-run phase is reported via a child component that only mounts when a run is active —
    // avoids opening an SSE stream for every user on every page (INC-886 pattern).
    const [cloudPhase, setCloudPhase] = useState<NavInstallationPhase | null>(null)
    const handlePhase = useRef(setCloudPhase)
    handlePhase.current = setCloudPhase

    // Derive the effective phase: prefer cloud progress when available, fall back to the logic phase.
    const effectivePhase: NavInstallationPhase = cloudPhase ?? logicPhase

    // Elapsed time — only meaningful for cloud runs (we have the kickoff timestamp).
    const startedAt = activeCloudRun?.startedAt ?? null
    const showElapsed = !!startedAt && isRunActive
    const now = useNow(showElapsed)
    const elapsedSeconds = startedAt ? elapsedSecondsFrom(startedAt, now) : 0

    // Pulse when the dot's phase changes.
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

    if (!shouldShow) {
        return null
    }

    const handleClick = (): void => {
        if (isRunActive) {
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
        <>
            {activeCloudRun && <CloudRunPhaseReporter handle={activeCloudRun} onPhase={handlePhase.current} />}
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
        </>
    )
}
