import { DiffEvidenceCard } from 'products/posthog_ai/frontend/api/tools'

import type { HogFunctionFieldDiff } from './hogFunctionConfigDiffUtils'

// A pseudo-path per field so the shared diff viewer picks the right syntax highlighting — JSON
// fields pretty-print as JSON; hog source has no registered grammar and falls back to plain text.
function fieldPath(diff: HogFunctionFieldDiff): string {
    return diff.kind === 'json' ? `${diff.field}.json` : `${diff.field}.txt`
}

/**
 * Approval-card preview for a `cdp-functions-partial-update`: one evidence card per changed field —
 * the field label and +/- line stats in the card's header bar, the full change in the shared diff
 * viewer, capped with a "Show all n lines" expander. Pure presentational — the diff is precomputed
 * by `buildHogFunctionConfigDiff`.
 */
export function HogFunctionConfigDiff({ diffs }: { diffs: HogFunctionFieldDiff[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 min-w-0">
            {diffs.map((diff) =>
                diff.truncated ? (
                    <div key={diff.field} className="text-xs text-secondary">
                        {diff.label}: large change — {diff.added} added, {diff.removed} removed lines
                    </div>
                ) : (
                    <DiffEvidenceCard
                        key={diff.field}
                        label={diff.label}
                        oldText={diff.currentText || null}
                        newText={diff.proposedText}
                        path={fieldPath(diff)}
                    />
                )
            )}
        </div>
    )
}
