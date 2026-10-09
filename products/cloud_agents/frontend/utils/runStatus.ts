import type { LemonTagType } from '@posthog/lemon-ui'

import {
    CloudAgentReasoningEffortEnumApi,
    CloudAgentRunStatusEnumApi,
    CloudAgentRunStatusReasonEnumApi,
    CloudAgentSessionStatusEnumApi,
    InferenceBillingEnumApi,
    InferenceModeEnumApi,
} from '../generated/api.schemas'

/** A run in these states has a sandbox or is waiting for one, so its data still changes. */
export function isRunActive(status: CloudAgentRunStatusEnumApi): boolean {
    return status === CloudAgentRunStatusEnumApi.Queued || status === CloudAgentRunStatusEnumApi.Running
}

/** A done run is final and refuses a message. */
export function isRunDone(status: CloudAgentRunStatusEnumApi): boolean {
    return status === CloudAgentRunStatusEnumApi.Done
}

export interface RunStatusDisplay {
    label: string
    type: LemonTagType
    tooltip?: string
}

/** The label of each status, for filters and for a run that has no reason yet. */
export const RUN_STATUS_DISPLAY: Record<CloudAgentRunStatusEnumApi, RunStatusDisplay> = {
    [CloudAgentRunStatusEnumApi.Queued]: { label: 'Queued', type: 'default' },
    [CloudAgentRunStatusEnumApi.Running]: { label: 'Running', type: 'highlight' },
    [CloudAgentRunStatusEnumApi.Idle]: { label: 'Idle', type: 'default' },
    [CloudAgentRunStatusEnumApi.Done]: { label: 'Done', type: 'muted' },
}

/** The label of an idle or done run. The API status detail replaces the tooltip when it has one. */
export const RUN_STATUS_REASON_DISPLAY: Record<CloudAgentRunStatusReasonEnumApi, RunStatusDisplay> = {
    [CloudAgentRunStatusReasonEnumApi.TurnClosed]: {
        label: 'Waiting for you',
        type: 'success',
        tooltip: 'The agent finished its turn. Send a message to continue.',
    },
    [CloudAgentRunStatusReasonEnumApi.ProvisionFailed]: { label: 'Could not start', type: 'danger' },
    [CloudAgentRunStatusReasonEnumApi.UnexpectedFailure]: { label: 'Failed', type: 'danger' },
    [CloudAgentRunStatusReasonEnumApi.TimedOut]: { label: 'Timed out', type: 'warning' },
    [CloudAgentRunStatusReasonEnumApi.CreditSpent]: { label: 'Usage limit reached', type: 'warning' },
    [CloudAgentRunStatusReasonEnumApi.Finished]: { label: 'Merged', type: 'completion' },
    [CloudAgentRunStatusReasonEnumApi.Closed]: { label: 'Closed', type: 'muted' },
    [CloudAgentRunStatusReasonEnumApi.Cancelled]: { label: 'Canceled', type: 'muted' },
}

/** The tag for a run: the reason decides the label when there is one, and the status decides it otherwise. */
export function getRunStatusDisplay(
    status: CloudAgentRunStatusEnumApi,
    reason: CloudAgentRunStatusReasonEnumApi | null,
    detail: string | null = null
): RunStatusDisplay {
    const display = (reason ? RUN_STATUS_REASON_DISPLAY[reason] : undefined) ??
        RUN_STATUS_DISPLAY[status] ?? { label: status, type: 'default' as const }
    return { ...display, tooltip: detail || display.tooltip }
}

export const SESSION_STATUS_DISPLAY: Record<CloudAgentSessionStatusEnumApi, RunStatusDisplay> = {
    [CloudAgentSessionStatusEnumApi.Queued]: { label: 'Queued', type: 'default' },
    [CloudAgentSessionStatusEnumApi.Running]: { label: 'Running', type: 'highlight' },
    [CloudAgentSessionStatusEnumApi.Ended]: { label: 'Ended', type: 'muted' },
}

export const REASONING_EFFORT_LABELS: Record<CloudAgentReasoningEffortEnumApi, string> = {
    [CloudAgentReasoningEffortEnumApi.Low]: 'Low',
    [CloudAgentReasoningEffortEnumApi.Medium]: 'Medium',
    [CloudAgentReasoningEffortEnumApi.High]: 'High',
    [CloudAgentReasoningEffortEnumApi.Xhigh]: 'Extra high',
    [CloudAgentReasoningEffortEnumApi.Max]: 'Max',
    [CloudAgentReasoningEffortEnumApi.Ultracode]: 'Ultracode',
}

export const INFERENCE_MODE_DISPLAY: Record<InferenceModeEnumApi, { label: string; description: string }> = {
    [InferenceModeEnumApi.Auto]: {
        label: 'Automatic',
        description: 'Uses your own subscription when one is connected, and PostHog AI credits when none is.',
    },
    [InferenceModeEnumApi.OwnSubscription]: {
        label: 'Your subscription',
        description: 'Model usage counts against your subscription. PostHog charges for compute only.',
    },
    [InferenceModeEnumApi.Posthog]: {
        label: 'PostHog AI credits',
        description: 'PostHog provides the model and bills the usage in AI credits.',
    },
}

export const INFERENCE_BILLING_LABELS: Record<InferenceBillingEnumApi, string> = {
    [InferenceBillingEnumApi.Posthog]: 'PostHog AI credits',
    [InferenceBillingEnumApi.OwnSubscription]: 'your subscription',
}
