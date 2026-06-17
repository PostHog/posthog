import { Tooltip } from '@posthog/lemon-ui'

/**
 * Hoverable "Why?" affix shown next to a priority or actionability tag, surfacing the per-report
 * judgment rationale as a tooltip. Deliberately not a tag itself (the priority/actionability chips
 * already are). Renders nothing when there's no explanation.
 */
export function JudgmentWhyLabel({ explanation }: { explanation?: string | null }): JSX.Element | null {
    if (!explanation?.trim()) {
        return null
    }
    return (
        <Tooltip title={explanation}>
            <span className="text-[10px] font-medium text-muted underline decoration-dotted underline-offset-2 cursor-help select-none">
                Why?
            </span>
        </Tooltip>
    )
}
