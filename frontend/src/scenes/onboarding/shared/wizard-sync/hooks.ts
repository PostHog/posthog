import { useActions, useMountedLogic, useValues } from 'kea'
import type React from 'react'
import { useEffect, useRef, useState } from 'react'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { installationProgressLogic } from './installationProgressLogic'
import { wizardActiveSessionDetectorLogic, watchWorkflowWhileMounted } from './wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from './workflows'

// 1Hz clock for the elapsed timer, scoped to a mounted run so nothing ticks when no run is active.
// `frozen` stops the interval entirely — a finished run shows its fixed duration, so ticking for it
// would be pure re-render churn.
export function useNow(frozen: boolean = false): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        if (frozen) {
            return
        }
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [frozen])
    return now
}

/** Seconds a run has been going: live-ticking until `endedAt` is known, then frozen at the final
 * duration. Returns 0 until `startedAt` exists. */
export function useRunElapsedSeconds(startedAt: string | null | undefined, endedAt?: string | null): number {
    const endMs = endedAt ? new Date(endedAt).getTime() : NaN
    const now = useNow(!Number.isNaN(endMs))
    return startedAt ? elapsedSecondsFrom(startedAt, Number.isNaN(endMs) ? now : endMs) : 0
}

/**
 * Whether a self-driving wizard run is going right now, for surfaces the run sends the user to
 * mid-flight (the GitHub connect round trip) that need to hand them back to their terminal.
 * Answers only for the self-driving program — an SDK-install run in flight returns false; ask the
 * detector's `activeWorkflowId` directly for the any-program question.
 *
 * Registers the program with the detector while mounted rather than relying on the onboarding
 * variant flag, because the wizard is also run standalone against accounts that are long past
 * onboarding — those users would otherwise never be watched.
 */
export function useSelfDrivingRunInFlight(): boolean {
    return useSelfDrivingRunState().inFlight
}

/**
 * The same question as `useSelfDrivingRunInFlight`, plus whether the detector has actually answered
 * it. Callers whose wrong branch is costly — sending someone into the app mid-run — need the
 * difference: `inFlight === false` is "no run" only once `resolved` is true, and before that it just
 * means nobody has polled yet. The detector's first poll is jittered up to 30s, so that window is
 * long enough to matter, which is why mounting here also asks for a targeted check.
 */
export function useSelfDrivingRunState(): { inFlight: boolean; resolved: boolean } {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { activeWorkflowId, hasResolvedSessionState } = useValues(wizardActiveSessionDetectorLogic)
    const { check } = useActions(wizardActiveSessionDetectorLogic)

    useEffect(() => watchWorkflowWhileMounted(SELF_DRIVING_WORKFLOW_ID), [])
    useEffect(() => {
        if (!hasResolvedSessionState) {
            check()
        }
        // Mount-only: a later unresolved state means a poll is already in flight or scheduled.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return { inFlight: activeWorkflowId === SELF_DRIVING_WORKFLOW_ID, resolved: hasResolvedSessionState }
}

/**
 * Whether a local wizard run should take over the install step: a session exists on the stream AND it
 * has been observed fresh (stale terminal rows from previous runs don't count). Mounts the local
 * Installation layer — and with it the wizard session stream — so use it only where the takeover can
 * actually render (the sync-enabled install steps).
 */
export function useLocalWizardRunActive(workflowId?: string): boolean {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'local', workflowId }))
    return installationProgress.isCurrent
}

/**
 * Hogfetti for a PR merged while the user is watching, exactly once per mount. Gated on the live
 * false → true transition: starts null so the first hydrated state (SSE replay / poll snapshot
 * arrives async after mount) arms the detector instead of reading as a transition — otherwise every
 * reload of a merged run re-fires. Quiet in the storybook test runner and under reduced motion.
 */
export function useMergeCelebration(prMerged: boolean): { CelebrationComponent: React.FC } {
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti()
    const prevMergedRef = useRef<boolean | null>(null)
    const mergeCelebratedRef = useRef(false)
    useEffect(() => {
        const prev = prevMergedRef.current
        prevMergedRef.current = prMerged
        if (prev === null || prev || !prMerged || mergeCelebratedRef.current) {
            return
        }
        if (inStorybookTestRunner() || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        mergeCelebratedRef.current = true
        triggerHogfetti()
    }, [prMerged, triggerHogfetti])
    return { CelebrationComponent: HogfettiComponent }
}
