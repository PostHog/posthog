import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import type { HogFunctionFieldDiff, HogFunctionFieldStatus } from './hogFunctionConfigDiff'

const STATUS_META: Record<HogFunctionFieldStatus, { label: string; type: 'success' | 'danger' | 'warning' }> = {
    added: { label: 'Added', type: 'success' },
    removed: { label: 'Removed', type: 'danger' },
    changed: { label: 'Changed', type: 'warning' },
}

function DiffStat({ added, removed }: { added: number; removed: number }): JSX.Element | null {
    if (added === 0 && removed === 0) {
        return null
    }
    return (
        <span className="font-mono text-xs shrink-0">
            <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
        </span>
    )
}

function ValueBlock({ text, tone }: { text: string; tone: 'current' | 'proposed' }): JSX.Element {
    return (
        <pre
            className={clsx(
                'm-0 whitespace-pre-wrap break-words rounded p-1.5 text-xs font-mono',
                tone === 'current' ? 'bg-danger-highlight text-danger' : 'bg-success-highlight text-success'
            )}
        >
            {text}
        </pre>
    )
}

/**
 * Compact approval-card preview for a `cdp-functions-partial-update`: one row per changed field with an
 * added/removed/changed tag, a +/- line-stat, and the before/after value. Huge fields collapse to the
 * stat summary. Pure presentational — the diff is precomputed by `buildHogFunctionConfigDiff`.
 */
export function HogFunctionConfigDiff({ diffs }: { diffs: HogFunctionFieldDiff[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {diffs.map((diff) => {
                const meta = STATUS_META[diff.status]
                return (
                    <div key={diff.field} className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                            <LemonTag type={meta.type} size="small">
                                {meta.label}
                            </LemonTag>
                            <span className="text-xs font-medium">{diff.label}</span>
                            <DiffStat added={diff.added} removed={diff.removed} />
                        </div>
                        {diff.truncated ? (
                            <div className="text-xs text-secondary">
                                Large change — {diff.added} added, {diff.removed} removed lines
                            </div>
                        ) : (
                            <div className="flex flex-col gap-1">
                                {diff.status !== 'added' && diff.currentText && (
                                    <ValueBlock text={diff.currentText} tone="current" />
                                )}
                                {diff.status !== 'removed' && diff.proposedText && (
                                    <ValueBlock text={diff.proposedText} tone="proposed" />
                                )}
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
