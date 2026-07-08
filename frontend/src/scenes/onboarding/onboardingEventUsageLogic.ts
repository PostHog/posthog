import { actions, connect, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, type FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { onboardingEventUsageLogicType } from './onboardingEventUsageLogicType'
import { resolveOnboardingFlowVariant } from './onboardingVariants'

/** Steps of the context-first onboarding flow (`ContextOnboarding.tsx`), in order. */
export type ContextOnboardingStepId = 'welcome' | 'install' | 'sources' | 'warehouse' | 'billing' | 'invite'

// GROW-89: both onboarding flows fire the same funnel event names during the transition, told apart
// by `version` (1 = legacy, 2 = context-first redesign) and `flow_variant`. Reusing names keeps
// every existing dashboard and alert on the v1 events working; the legacy flow's events live in
// `eventUsageLogic`, stamped `{version: 1, flow_variant: 'legacy'}`.
const CONTEXT_ONBOARDING_EVENT_PROPS = { version: 2, flow_variant: 'context_first' } as const

/** Arm of the cloud-wizard AB test (GROW-117): `test` offers the cloud run, `control` is local-only. */
export type CloudRunExperimentArm = 'control' | 'test'

/**
 * The user's experiment arm, or null when they are not enrolled: an unset/boolean flag value (not
 * rolled out, targeting excludes them, flags not loaded yet) must NOT be collapsed into `control`,
 * or never-enrolled users pollute the control cohort and bias the readout toward "no effect".
 */
export function resolveCloudRunExperimentArm(featureFlags: FeatureFlagsSet): CloudRunExperimentArm | null {
    const value = featureFlags[FEATURE_FLAGS.ONBOARDING_WIZARD_CLOUD_RUN]
    return value === 'test' || value === 'control' ? value : null
}

// Wizard-sync events fire from BOTH onboarding variants (GROW-121): same v2 event shape, but
// flow_variant reflects whichever flow the user is actually in, and the cloud-run experiment arm
// rides along (GROW-117) so downstream metrics can split on either without a flag-persons join.
function wizardSyncEventProps(featureFlags: FeatureFlagsSet): {
    version: 2
    flow_variant: string
    cloud_run_experiment_arm: CloudRunExperimentArm | null
} {
    return {
        version: 2,
        flow_variant: resolveOnboardingFlowVariant(featureFlags) === 'self-driving' ? 'context_first' : 'legacy',
        cloud_run_experiment_arm: resolveCloudRunExperimentArm(featureFlags),
    }
}

// Once-per-run guards for the completed-handoff funnel (exposure → CTA shown → CTA clicked). The
// same run renders on several surfaces (inline panel, FAB card, dialog) and those remount freely —
// deduping here, keyed by run, keeps the funnel's denominators honest without every surface
// carrying its own guard.
const reportedHandoffShownRuns = new Set<string>()
const reportedDashboardCtaShownRuns = new Set<string>()

export function resetCloudRunExperimentExposureForTests(): void {
    reportedHandoffShownRuns.clear()
    reportedDashboardCtaShownRuns.clear()
}

/**
 * Funnel events for the context-first onboarding flow (v2) — a dedicated logic rather than more
 * surface on the giant `eventUsageLogic`, following `sessionRecordingEventUsageLogic`'s split.
 * Shared funnel signals (started, step completed/skipped, completed) reuse the legacy event names
 * with `version: 2`; signals the legacy flow doesn't have (step viewed, install mode, source
 * toggles, plan, cloud run) get their own names.
 */
export const onboardingEventUsageLogic = kea<onboardingEventUsageLogicType>([
    path(['scenes', 'onboarding', 'onboardingEventUsageLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        reportContextOnboardingStarted: true,
        reportContextOnboardingStepViewed: (stepId: ContextOnboardingStepId) => ({ stepId }),
        reportContextOnboardingStepCompleted: (stepId: ContextOnboardingStepId) => ({ stepId }),
        reportContextOnboardingStepSkipped: (stepId: ContextOnboardingStepId) => ({ stepId }),
        reportContextOnboardingCompleted: (productKey: string) => ({ productKey }),
        reportContextOnboardingInstallModeSelected: (mode: 'cloud' | 'local') => ({ mode }),
        reportContextOnboardingSourceToggled: (productKey: string, toggle: string, enabled: boolean) => ({
            productKey,
            toggle,
            enabled,
        }),
        reportContextOnboardingPlanSelected: (plan: 'free' | 'pay_as_you_go') => ({ plan }),
        // Cloud-run funnel events mirror the backend `task_run_created` / `task_run_completed`
        // lifecycle events (products/tasks/backend/models.py) and reuse their property names.
        reportContextOnboardingCloudRunQueued: (props: { taskId: string; runId: string; repository: string }) => props,
        reportContextOnboardingCloudRunCompleted: (props: {
            taskId: string
            runId: string
            status: 'completed' | 'failed' | 'cancelled'
            durationSeconds: number | null
            prOpened: boolean
            prUrl: string | null
        }) => props,
        // Engagement with the shared wizard sync surface (FAB card / launcher / dialog), fired for
        // both variants and both run modes (GROW-121).
        reportWizardSyncExpanded: (props: { runKey: string; mode: 'cloud' | 'local'; phase: string }) => props,
        reportWizardSyncMinimized: (props: { runKey: string; mode: 'cloud' | 'local'; phase: string }) => props,
        reportWizardSyncRestored: (props: { runKey: string; mode: 'cloud' | 'local'; phase: string }) => props,
        reportWizardSyncRunDismissed: (props: {
            runKey: string
            mode: 'cloud' | 'local'
            phase: string
            elapsedSeconds: number
        }) => props,
        // The completed-handoff funnel: exposure (a run's completed state rendered anywhere), the
        // dashboard CTA becoming visible, and the CTA click. Deduped per run per pageload here, so
        // surfaces can report unconditionally. No dashboard names or ids — same rule as repo names.
        reportWizardSyncHandoffShown: (props: {
            runKey: string
            mode: 'cloud' | 'local'
            surface: 'inline' | 'fab'
            prOpened: boolean
        }) => props,
        reportWizardSyncDashboardCtaShown: (props: {
            runKey: string
            mode: 'cloud' | 'local'
            surface: 'inline' | 'fab'
        }) => props,
        reportWizardSyncDashboardCtaClicked: (props: {
            runKey: string
            mode: 'cloud' | 'local'
            surface: 'inline' | 'fab'
        }) => props,
    }),
    listeners(({ values }) => ({
        // The flow always enters at the welcome step, so `started` carries a fixed entry point
        // (legacy uses e.g. 'product_selection').
        reportContextOnboardingStarted: () => {
            posthog.capture('onboarding started', {
                entry_point: 'welcome',
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingStepViewed: ({ stepId }) => {
            posthog.capture('onboarding step viewed', {
                step_key: stepId,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingStepCompleted: ({ stepId }) => {
            posthog.capture('onboarding step completed', {
                step_key: stepId,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingStepSkipped: ({ stepId }) => {
            posthog.capture('onboarding step skipped', {
                step_key: stepId,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingCompleted: ({ productKey }) => {
            posthog.capture('onboarding completed', {
                product_key: productKey,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingInstallModeSelected: ({ mode }) => {
            posthog.capture('onboarding install mode selected', {
                mode,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportContextOnboardingSourceToggled: ({ productKey, toggle, enabled }) => {
            posthog.capture('onboarding context source toggled', {
                product_key: productKey,
                toggle,
                enabled,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingPlanSelected: ({ plan }) => {
            posthog.capture('onboarding plan selected', {
                plan,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        // Deliberately NOT capturing the repository name or PR URL: they identify customers'
        // (often private) repos and this event lands in the shared app analytics project. The
        // backend task_run_* lifecycle events carry them server-side; task_id/run_id join to them.
        reportContextOnboardingCloudRunQueued: ({ taskId, runId }) => {
            posthog.capture('onboarding cloud run queued', {
                task_id: taskId,
                run_id: runId,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportContextOnboardingCloudRunCompleted: ({ taskId, runId, status, durationSeconds, prOpened }) => {
            posthog.capture('onboarding cloud run completed', {
                task_id: taskId,
                run_id: runId,
                status,
                duration_seconds: durationSeconds,
                pr_opened: prOpened,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncExpanded: ({ runKey, mode, phase }) => {
            posthog.capture('wizard sync expanded', {
                run_key: runKey,
                mode,
                phase,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncMinimized: ({ runKey, mode, phase }) => {
            posthog.capture('wizard sync minimized', {
                run_key: runKey,
                mode,
                phase,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncRestored: ({ runKey, mode, phase }) => {
            posthog.capture('wizard sync restored', {
                run_key: runKey,
                mode,
                phase,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncRunDismissed: ({ runKey, mode, phase, elapsedSeconds }) => {
            posthog.capture('wizard sync run dismissed', {
                run_key: runKey,
                mode,
                phase,
                elapsed_seconds: elapsedSeconds,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncHandoffShown: ({ runKey, mode, surface, prOpened }) => {
            if (reportedHandoffShownRuns.has(runKey)) {
                return
            }
            reportedHandoffShownRuns.add(runKey)
            posthog.capture('wizard sync handoff shown', {
                run_key: runKey,
                mode,
                surface,
                pr_opened: prOpened,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        reportWizardSyncDashboardCtaShown: ({ runKey, mode, surface }) => {
            if (reportedDashboardCtaShownRuns.has(runKey)) {
                return
            }
            reportedDashboardCtaShownRuns.add(runKey)
            posthog.capture('wizard sync dashboard cta shown', {
                run_key: runKey,
                mode,
                surface,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
        // Clicks are NOT deduped: a user returning to the dashboard through the CTA twice is real
        // engagement, and the shown-event denominator is already stable.
        reportWizardSyncDashboardCtaClicked: ({ runKey, mode, surface }) => {
            posthog.capture('wizard sync dashboard cta clicked', {
                run_key: runKey,
                mode,
                surface,
                ...wizardSyncEventProps(values.featureFlags),
            })
        },
    })),
])
