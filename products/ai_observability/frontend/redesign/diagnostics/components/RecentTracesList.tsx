import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceListItemApi, TracePreviewApi } from '../../../generated/api.schemas'
import { ListErrorState } from '../../lists/components/ListErrorState'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { MISSING_REASON_LABELS } from '../../traces/components/TracePreviewCell'

export interface RecentTracesListProps {
    traces: TraceCellLoad<TraceListItemApi[]>
    previews: CellLoads<TracePreviewApi>
    /** What the list says when the read found no trace. */
    emptyMessage: string
    /** What a trace says when its input failed to load. */
    inputFailedMessage: string
    onRetry: () => void
    onOpenTrace: (trace: TraceListItemApi) => void
    /** The drawer's data-attr, which the list's controls suffix. */
    'data-attr': string
}

// The input is the customer's own prompt. ph-sensitive keeps the click on the row in autocapture without its text, and
// ph-mask masks the text in session replay.
function inputOf(preview: TraceCellLoad<TracePreviewApi> | undefined): JSX.Element | null {
    const value = preview?.status === 'ready' ? preview.value : null
    if (value?.input) {
        return <span className="ph-sensitive ph-mask min-w-0 truncate">{value.input}</span>
    }
    return value?.inputMissingReason ? (
        <span className="text-muted whitespace-nowrap">{MISSING_REASON_LABELS[value.inputMissingReason]}</span>
    ) : null
}

export function RecentTracesList({
    traces,
    previews,
    emptyMessage,
    inputFailedMessage,
    onRetry,
    onOpenTrace,
    'data-attr': dataAttr,
}: RecentTracesListProps): JSX.Element {
    if (traces.status === 'loading') {
        return <LemonSkeleton repeat={5} className="h-8" />
    }
    if (traces.status === 'error') {
        return (
            <ListErrorState
                title="Could not load recent traces"
                description="Try again. If it keeps happening, contact support."
                retry={{ onClick: onRetry, 'data-attr': `${dataAttr}-recent-traces-retry` }}
            />
        )
    }
    if (traces.value.length === 0) {
        return <p className="m-0 text-secondary">{emptyMessage}</p>
    }
    return (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {traces.value.map((trace) => (
                <li key={trace.id}>
                    <LemonButton
                        fullWidth
                        size="small"
                        onClick={() => onOpenTrace(trace)}
                        data-attr={`${dataAttr}-recent-trace`}
                    >
                        <span className="flex w-full min-w-0 items-center justify-between gap-3 font-normal">
                            <TraceCellValue
                                status={previews.get(trace.id)?.status ?? 'loading'}
                                skeletonWidth="w-32"
                                failedMessage={inputFailedMessage}
                            >
                                {inputOf(previews.get(trace.id))}
                            </TraceCellValue>
                            <TZLabel
                                time={trace.createdAt}
                                showPopover={false}
                                className="shrink-0 text-xs text-secondary"
                            />
                        </span>
                    </LemonButton>
                </li>
            ))}
        </ul>
    )
}
