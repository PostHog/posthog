import { cn } from 'lib/utils/css-classes'

import type { TraceListItemApi, TracePreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TraceCellValue } from '../../traces/components/TraceCellValue'

const PREVIEW_FAILED = "Couldn't load this trace's input."

export interface RecentTraceRowProps {
    trace: TraceListItemApi
    preview: TraceCellLoad<TracePreviewApi>
    onOpen: (traceId: string) => void
}

export function RecentTraceRow({ trace, preview, onOpen }: RecentTraceRowProps): JSX.Element {
    const input = preview.status === 'ready' ? preview.value.input : null
    return (
        <li>
            <button
                type="button"
                onClick={() => onOpen(trace.id)}
                className="flex w-full min-w-0 cursor-pointer flex-col gap-0.5 rounded border border-primary bg-surface-primary px-2 py-1.5 text-left hover:bg-fill-highlight-100"
                // pinned: autocapture dashboards select a recent trace by this value
                data-attr="ai-observability-person-drawer-trace"
            >
                <span className="flex w-full min-w-0 items-center gap-2">
                    <span className={cn('min-w-0 truncate', trace.name === null ? 'text-muted' : 'font-semibold')}>
                        {trace.name ?? 'Untitled trace'}
                    </span>
                    <span className="ml-auto shrink-0 text-xs text-secondary">
                        <ShortTimestamp time={trace.createdAt} />
                    </span>
                </span>
                <span className="w-full min-w-0 text-xs text-secondary">
                    <TraceCellValue status={preview.status} skeletonWidth="w-48" failedMessage={PREVIEW_FAILED}>
                        {input !== null ? (
                            // The input is a customer's prompt, so autocapture must not record it.
                            <span title={input} className="ph-no-capture block truncate">
                                {input}
                            </span>
                        ) : null}
                    </TraceCellValue>
                </span>
            </button>
        </li>
    )
}
