import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ErrorListItemApi, TraceListItemApi, TracePreviewApi } from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { EntityDetailChart } from '../../diagnostics/components/EntityDetailChart'
import { RecentTracesList } from '../../diagnostics/components/RecentTracesList'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { EntityDrawer, EntityDrawerProps, EntityDrawerTile } from '../../shared/components/EntityDrawer'
import type { ErrorDetailLoad } from '../errorDrawerLogic'

// pinned: data-attrs feed autocapture; dashboards and tests find the drawer and its controls by this value and its suffixes
const DATA_ATTR = 'error-drawer'
const TILE_LABELS = ['Occurrences', 'Traces', 'Users', 'Last seen']

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
                <EntityDetailChart
                    detail={detail}
                    timezone={timezone}
                    notFound={{
                        title: 'No occurrences in this date range',
                        description:
                            "This error didn't occur in the selected date range. Pick a wider date range to see it.",
                    }}
                    failedTitle="Could not load this error"
                    onRetry={onRetry}
                    data-attr={DATA_ATTR}
                />
            }
            sections={[
                {
                    title: 'Recent traces',
                    content: (
                        <RecentTracesList
                            traces={recentTraces}
                            previews={previews}
                            emptyMessage="No traces with this error match the filters."
                            inputFailedMessage="Couldn't load the input. Reopen the error to try again."
                            onRetry={onRetry}
                            onOpenTrace={onOpenTrace}
                            data-attr={DATA_ATTR}
                        />
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
