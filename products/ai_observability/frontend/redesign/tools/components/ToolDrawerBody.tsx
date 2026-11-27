import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type {
    ToolGroupDetailApi,
    ToolListItemApi,
    TraceListItemApi,
    TracePreviewApi,
} from '../../../generated/api.schemas'
import { ChangeTag } from '../../diagnostics/components/ChangeTag'
import { EntityDetailChart } from '../../diagnostics/components/EntityDetailChart'
import { RecentTracesList } from '../../diagnostics/components/RecentTracesList'
import type { DetailLoad } from '../../diagnostics/diagnosticsDrawerReads'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { EntityDrawer, EntityDrawerProps, EntityDrawerTile } from '../../shared/components/EntityDrawer'
import type { ToolTraceSection } from '../toolDrawerLogic'
import { FailureRateCell } from './FailureRateCell'

// pinned: data-attrs feed autocapture; dashboards and tests find the drawer and its controls by this value and its suffixes
const DATA_ATTR = 'tool-drawer'
const TILE_LABELS = ['Calls', 'Traces', 'Failure rate', 'Last seen']

export interface ToolDrawerBodyProps extends Pick<
    EntityDrawerProps,
    'rect' | 'width' | 'resizer' | 'containerRef' | 'onClose'
> {
    /** Null until the row or the detail gives it. */
    name: string | null
    /** The tool's row, from the list or the detail. Null until one of them is known. */
    item: ToolListItemApi | null
    detail: DetailLoad<ToolGroupDetailApi>
    showsFailures: boolean
    recentFailures: TraceCellLoad<TraceListItemApi[]>
    recentCalls: TraceCellLoad<TraceListItemApi[]>
    previews: CellLoads<TracePreviewApi>
    timezone: string
    /** Null until the tool's name is known. */
    viewAllHref: string | null
    onRetry: () => void
    onOpenTrace: (section: ToolTraceSection, trace: TraceListItemApi) => void
}

function tilesOf(item: ToolListItemApi | null, detail: DetailLoad<ToolGroupDetailApi>): EntityDrawerTile[] {
    if (item) {
        return [
            { label: 'Calls', value: humanFriendlyNumber(item.calls) },
            { label: 'Traces', value: humanFriendlyNumber(item.traces) },
            { label: 'Failure rate', value: <FailureRateCell tool={item} /> },
            { label: 'Last seen', value: <TZLabel time={item.lastSeen} /> },
        ]
    }
    // With no row and a settled detail, the chart's place says why the numbers are missing.
    return detail.status === 'loading' ? TILE_LABELS.map((label) => ({ label, value: null, loading: true })) : []
}

export function ToolDrawerBody({
    name,
    item,
    detail,
    showsFailures,
    recentFailures,
    recentCalls,
    previews,
    timezone,
    viewAllHref,
    onRetry,
    onOpenTrace,
    ...panelProps
}: ToolDrawerBodyProps): JSX.Element {
    const recentList = (
        section: ToolTraceSection,
        traces: TraceCellLoad<TraceListItemApi[]>,
        emptyMessage: string
    ): JSX.Element => (
        <RecentTracesList
            traces={traces}
            previews={previews}
            emptyMessage={emptyMessage}
            inputFailedMessage="Couldn't load the input. Reopen the tool to try again."
            onRetry={onRetry}
            onOpenTrace={(trace) => onOpenTrace(section, trace)}
            data-attr={DATA_ATTR}
        />
    )
    return (
        <EntityDrawer
            {...panelProps}
            aria-label="Tool detail"
            data-attr={DATA_ATTR}
            // The name comes from the customer's own instrumentation, so autocapture and session replay must not record it.
            title={
                name === null ? (
                    detail.status === 'loading' ? (
                        <LemonSkeleton className="h-4 w-60" />
                    ) : (
                        'Tool'
                    )
                ) : (
                    <span className="ph-no-capture font-mono text-sm">{name}</span>
                )
            }
            tag={item?.changeLabel ? <ChangeTag label={item.changeLabel} tone={item.changeTone} /> : undefined}
            tiles={tilesOf(item, detail)}
            chart={
                <EntityDetailChart
                    detail={detail}
                    timezone={timezone}
                    notFound={{
                        title: 'No calls in this date range',
                        description:
                            "This tool wasn't called in the selected date range. Pick a wider date range to see it.",
                    }}
                    failedTitle="Could not load this tool"
                    onRetry={onRetry}
                    data-attr={DATA_ATTR}
                />
            }
            sections={[
                {
                    title: 'Recent failures',
                    content: showsFailures
                        ? recentList(
                              'failures',
                              recentFailures,
                              'No traces with a failure of this tool match the filters.'
                          )
                        : null,
                },
                {
                    title: 'Recent calls',
                    content: recentList('calls', recentCalls, 'No traces that called this tool match the filters.'),
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
