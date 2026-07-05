import { actions, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import type { onboardingEventUsageLogicType } from './onboardingEventUsageLogicType'

/** Steps of the context-first onboarding flow (`ContextOnboarding.tsx`), in order. */
export type ContextOnboardingStepId = 'welcome' | 'install' | 'sources' | 'warehouse' | 'billing' | 'invite'

// GROW-89: both onboarding flows fire the same funnel event names during the transition, told apart
// by `version` (1 = legacy, 2 = context-first redesign) and `flow_variant`. Reusing names keeps
// every existing dashboard and alert on the v1 events working; the legacy flow's events live in
// `eventUsageLogic`, stamped `{version: 1, flow_variant: 'legacy'}`.
const CONTEXT_ONBOARDING_EVENT_PROPS = { version: 2, flow_variant: 'context_first' } as const

/**
 * Funnel events for the context-first onboarding flow (v2) — a dedicated logic rather than more
 * surface on the giant `eventUsageLogic`, following `sessionRecordingEventUsageLogic`'s split.
 * Shared funnel signals (started, step completed/skipped, completed) reuse the legacy event names
 * with `version: 2`; signals the legacy flow doesn't have (step viewed, install mode, source
 * toggles, plan, cloud run) get their own names.
 */
export const onboardingEventUsageLogic = kea<onboardingEventUsageLogicType>([
    path(['scenes', 'onboarding', 'onboardingEventUsageLogic']),
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
    }),
    listeners({
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
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
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
        reportContextOnboardingCloudRunQueued: ({ taskId, runId, repository }) => {
            posthog.capture('onboarding cloud run queued', {
                task_id: taskId,
                run_id: runId,
                repository,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
        reportContextOnboardingCloudRunCompleted: ({ taskId, runId, status, durationSeconds, prOpened, prUrl }) => {
            posthog.capture('onboarding cloud run completed', {
                task_id: taskId,
                run_id: runId,
                status,
                duration_seconds: durationSeconds,
                pr_opened: prOpened,
                pr_url: prUrl,
                ...CONTEXT_ONBOARDING_EVENT_PROPS,
            })
        },
    }),
])
