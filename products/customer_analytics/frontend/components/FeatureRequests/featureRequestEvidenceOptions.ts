export const FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS: { value: string; label: string }[] = [
    { value: 'conversation', label: 'Customer conversation' },
    { value: 'slack', label: 'Slack' },
    { value: 'zendesk', label: 'Zendesk' },
    { value: 'email', label: 'Email' },
    { value: 'meeting', label: 'Meeting' },
    { value: 'buildbetter', label: 'BuildBetter' },
    { value: 'other', label: 'Other' },
]

const FEATURE_REQUEST_EVIDENCE_SOURCE_LABELS = Object.fromEntries(
    FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS.map(({ value, label }) => [value, label])
)

export function featureRequestEvidenceSourceLabel(source: string): string {
    return FEATURE_REQUEST_EVIDENCE_SOURCE_LABELS[source] ?? source
}
