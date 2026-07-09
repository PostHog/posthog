// Port of desktop `packages/shared/src/dismissal-reasons.ts`. Canonical dismiss /
// suppress reasons shown in the inbox. Values are persisted on dismissal artefacts
// by the backend `state` action – add or reorder options here only, and keep the
// values in sync with desktop.

export const DISMISSAL_REASON_OPTIONS = [
    {
        value: 'already_fixed',
        label: 'Already fixed',
        snoozesInsteadOfDismiss: true,
    },
    {
        value: 'report_unclear',
        label: 'Report is unclear to me',
    },
    {
        value: 'analysis_wrong',
        label: "Agent's analysis is wrong",
    },
    {
        value: 'wontfix_intentional',
        label: "Won't fix - intentional behavior",
    },
    {
        value: 'wontfix_irrelevant',
        label: "Won't fix - issue is real but insignificant",
    },
    { value: 'other', label: 'Something else…' },
] as const

/** Persisted dismissal / suppress reason (values match {@link DISMISSAL_REASON_OPTIONS}). */
export type DismissalReasonValue = (typeof DISMISSAL_REASON_OPTIONS)[number]['value']

/** Whether the given reason snoozes the report (temporarily) instead of permanently dismissing it. */
export function isDismissalReasonSnooze(value: DismissalReasonValue): boolean {
    const option = DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)
    return option != null && 'snoozesInsteadOfDismiss' in option && option.snoozesInsteadOfDismiss === true
}

/** Human label for a persisted dismissal reason code, or the raw code if it's not a known option. */
export function dismissalReasonLabel(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    return DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)?.label ?? value
}
