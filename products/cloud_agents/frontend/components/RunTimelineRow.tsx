import { IconTerminal } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { TimelineRow } from '../utils/runEvents'

export function RunTimelineRow({ row }: { row: TimelineRow }): JSX.Element {
    if (row.kind === 'assistant' || row.kind === 'user') {
        return (
            <div className="flex flex-col gap-1 min-w-0">
                <span className="text-secondary text-xs font-semibold">{row.title}</span>
                <div
                    className={
                        row.kind === 'user'
                            ? 'rounded border bg-surface-secondary px-3 py-2 break-words'
                            : 'break-words'
                    }
                    translate="no"
                >
                    <LemonMarkdown lowKeyHeadings disableImages="all">
                        {row.body ?? ''}
                    </LemonMarkdown>
                </div>
            </div>
        )
    }
    if (row.kind === 'tool') {
        return (
            <div className="flex items-start gap-2 min-w-0 text-xs">
                <IconTerminal className="text-secondary mt-0.5 shrink-0 text-base" />
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium break-all" translate="no">
                            {row.title}
                        </span>
                        {row.status && (
                            <LemonTag size="small" type={row.status === 'failed' ? 'danger' : 'muted'}>
                                {row.status.replace(/_/g, ' ')}
                            </LemonTag>
                        )}
                    </div>
                    {row.body && (
                        <code className="text-secondary truncate" title={row.body} translate="no">
                            {row.body}
                        </code>
                    )}
                </div>
            </div>
        )
    }
    return (
        <div className="text-secondary flex flex-wrap items-baseline gap-x-2 text-xs min-w-0">
            <span className={row.kind === 'status' ? 'font-medium' : undefined}>{row.title}</span>
            {row.body && (
                <span className="break-words" translate="no">
                    {row.body}
                </span>
            )}
        </div>
    )
}
