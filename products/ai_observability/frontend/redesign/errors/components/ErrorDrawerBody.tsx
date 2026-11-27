import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ErrorListItemApi, TraceListItemApi, TracePreviewApi } from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { EntityTrendChart } from '../../diagnostics/components/EntityTrendChart'
import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { EntityDrawer, EntityDrawerProps, EntityDrawerTile } from '../../shared/components/EntityDrawer'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { MISSING_REASON_LABELS } from '../../traces/components/TracePreviewCell'
import type { ErrorDetailLoad } from '../errorDrawerLogic'

// pinned: data-attrs feed autocapture; dashboards and tests find the drawer and its controls by this value and its suffixes
const DATA_ATTR = 'error-drawer'
const TILE_LABELS = ['Occurrences', 'Traces', 'Users', 'Last seen']
const RETRY_DESCRIPTION = 'Try again. If it keeps happening, contact support.'

export interface ErrorDrawerBodyProps extends Pick<
    EntityDrawerProps,
    'rect' | 'width' | 'resizer' | 'containerRef' | 'onClose'
> {
    /** Null until the row or the detail gives it. */
    message: string | null
    /** The error's row, from the list or the detail. Null until one of them is known. */
    item: ErrorListItemApi | null
    /** Whether the error is new to the range, which its first seen read says. False until that read lands. */
    isNew: boolean
    detail: ErrorDetailLoad
    recentTraces: TraceCellLoad<TraceListItemApi[]>
    previews: CellLoads<TracePreviewApi>
    timezone: string
    /** Null until the error's message is known. */
    viewAllHref: string | null
    onRetry: () => void
    onOpenTrace: (trace: TraceListItemApi) => void
}

function tilesOf(item: ErrorListItemApi | null, detail: ErrorDetailLoad): EntityDrawerTile[] {
    if (item) {
        return [
            { label: 'Occurrences', value: humanFriendlyNumber(item.occurrences) },
            { label: 'Traces', value: humanFriendlyNumber(item.traces) },
            { label: 'Users', value: humanFriendlyNumber(item.users) },
            { label: 'Last seen', value: <TZLabel time={item.lastSeen} /> },
        ]
    }
    // With no row and a settled detail, the chart's place says why the numbers are missing.
    return detail.status === 'loading' ? TILE_LABELS.map((label) => ({ label, value: null, loading: true })) : []
}

// The input is the customer's own prompt. ph-sensitive keeps the click on the row in autocapture without its text, and
// ph-mask masks the text in session replay.
function RecentTraceInput({ preview }: { preview: TraceCellLoad<TracePreviewApi> | undefined }): JSX.Element {
    const value = preview?.status === 'ready' ? preview.value : null
    return (
        <TraceCellValue
            status={preview?.status ?? 'loading'}
            skeletonWidth="w-32"
            failedMessage="Couldn't load the input. Reopen the error to try again."
        >
            {value?.input ? (
                <span className="ph-sensitive ph-mask min-w-0 truncate">{value.input}</span>
            ) : value?.inputMissingReason ? (
                <span className="text-muted whitespace-nowrap">{MISSING_REASON_LABELS[value.inputMissingReason]}</span>
            ) : null}
        </TraceCellValue>
    )
}

export function ErrorDrawerBody({
    message,
    item,
    isNew,
    detail,
    recentTraces,
    previews,
    timezone,
    viewAllHref,
    onRetry,
    onOpenTrace,
    ...panelProps
}: ErrorDrawerBodyProps): JSX.Element {
    return (
        <EntityDrawer
            {...panelProps}
            aria-label="Error detail"
            data-attr={DATA_ATTR}
            // The message is the customer's own error text, so autocapture and session replay must not record it.
            title={
                message === null ? (
                    detail.status === 'loading' ? (
                        <LemonSkeleton className="h-4 w-60" />
                    ) : (
                        'Error'
                    )
                ) : (
                    <span className="ph-no-capture font-mono text-sm">{message}</span>
                )
            }
            tag={
                item?.changeLabel || isNew ? (
                    <span className="flex flex-wrap gap-1">
                        {item?.changeLabel ? <ChangeTag label={item.changeLabel} tone={item.changeTone} /> : null}
                        {isNew ? (
                            <LemonTag type="highlight" size="small">
                                New
                            </LemonTag>
                        ) : null}
                    </span>
                ) : undefined
            }
            tiles={tilesOf(item, detail)}
            chart={
                detail.status === 'ready' ? (
                    <div className="rounded border p-3">
                        <EntityTrendChart
                            series={detail.value.item.series}
                            previousSeries={detail.value.previousSeries}
                            bucketStarts={detail.value.bucketStarts}
                            timezone={timezone}
                        />
                    </div>
                ) : detail.status === 'not_found' ? (
                    <ListEmptyState
                        title="No occurrences in this date range"
                        description="This error didn't occur in the selected date range. Pick a wider date range to see it."
                    />
                ) : detail.status === 'error' ? (
                    <ListErrorState
                        title="Could not load this error"
                        description={RETRY_DESCRIPTION}
                        retry={{ onClick: onRetry, 'data-attr': `${DATA_ATTR}-retry` }}
                    />
                ) : (
                    <LemonSkeleton className="h-54" />
                )
            }
            sections={[
                {
                    title: 'Recent traces',
                    content:
                        recentTraces.status === 'loading' ? (
                            <LemonSkeleton repeat={5} className="h-8" />
                        ) : recentTraces.status === 'error' ? (
                            <ListErrorState
                                title="Could not load recent traces"
                                description={RETRY_DESCRIPTION}
                                retry={{ onClick: onRetry, 'data-attr': `${DATA_ATTR}-recent-traces-retry` }}
                            />
                        ) : recentTraces.value.length === 0 ? (
                            <p className="m-0 text-secondary">No traces with this error match the filters.</p>
                        ) : (
                            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                                {recentTraces.value.map((trace) => (
                                    <li key={trace.id}>
                                        <LemonButton
                                            fullWidth
                                            size="small"
                                            onClick={() => onOpenTrace(trace)}
                                            data-attr={`${DATA_ATTR}-recent-trace`}
                                        >
                                            <span className="flex w-full min-w-0 items-center justify-between gap-3 font-normal">
                                                <RecentTraceInput preview={previews.get(trace.id)} />
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
                        ),
                },
            ]}
            footer={
                viewAllHref === null ? undefined : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={viewAllHref}
                        sideIcon={<IconArrowRight />}
                        data-attr={`${DATA_ATTR}-view-all`}
                    >
                        View all in Activity
                    </LemonButton>
                )
            }
        />
    )
}
