import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { QuickstartToolStatus } from '../quickstartLogic'

/** One line of card status: a stat when the tool has one, a plain state otherwise.
 * Unlike the full page's activity summary this never nests a link, so the whole
 * card stays clickable. */
export function ToolStatusLine({ status }: { status: QuickstartToolStatus }): JSX.Element {
    if (status.stat) {
        return (
            <div className="flex items-baseline gap-1.5 min-h-5 min-w-0">
                <span className="size-1.5 rounded-full bg-success shrink-0" />
                <span className="text-sm font-semibold tabular-nums text-primary">
                    {humanFriendlyLargeNumber(status.stat.value)}
                </span>
                <span className="text-sm text-secondary truncate">{status.stat.label}</span>
            </div>
        )
    }
    if (status.level === 'live') {
        return (
            <div className="flex items-center gap-1.5 min-h-5 min-w-0">
                <span className="size-1.5 rounded-full bg-success shrink-0" />
                <span className="text-sm text-secondary">Active in the last 30 days</span>
            </div>
        )
    }
    if (status.level === 'ready') {
        return (
            <div className="flex items-center gap-1.5 min-h-5 min-w-0">
                <span className="relative flex items-center justify-center size-2">
                    <span className="absolute size-2 rounded-full bg-warning opacity-25 animate-pulse" />
                    <span className="relative size-1.5 rounded-full bg-warning" />
                </span>
                <span className="text-sm text-secondary">Waiting for first signal</span>
            </div>
        )
    }
    return (
        <div className="flex items-center gap-1.5 min-h-5 min-w-0">
            <span className="size-1.5 rounded-full bg-muted-alt shrink-0" />
            <span className="text-sm text-secondary">Not collecting data yet</span>
        </div>
    )
}
