import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { QuickstartToolStatus } from '../quickstartLogic'

/** Same size-2 hit box for every dot so text starts at the same x across cards */
function StatusDot({ color, pulse = false }: { color: string; pulse?: boolean }): JSX.Element {
    return (
        <span className="relative flex items-center justify-center size-2 shrink-0">
            {pulse && <span className={`absolute size-2 rounded-full ${color} opacity-25 animate-pulse`} />}
            <span className={`relative size-1.5 rounded-full ${color}`} />
        </span>
    )
}

/** One line of card status: a stat when the tool has one, a plain state otherwise.
 * Unlike the full page's activity summary this never nests a link, so the whole
 * card stays clickable. */
export function ToolStatusLine({ status }: { status: QuickstartToolStatus }): JSX.Element {
    if (status.stat) {
        return (
            <span className="flex items-baseline gap-1.5 min-h-5 min-w-0">
                <StatusDot color="bg-success" />
                <span className="text-sm font-semibold tabular-nums text-primary">
                    {humanFriendlyLargeNumber(status.stat.value)}
                </span>
                <span className="text-sm text-secondary truncate">{status.stat.label}</span>
            </span>
        )
    }
    if (status.level === 'live') {
        return (
            <span className="flex items-center gap-1.5 min-h-5 min-w-0">
                <StatusDot color="bg-success" />
                <span className="text-sm text-secondary">Active in the last 30 days</span>
            </span>
        )
    }
    if (status.level === 'ready') {
        return (
            <span className="flex items-center gap-1.5 min-h-5 min-w-0">
                <StatusDot color="bg-warning" pulse />
                <span className="text-sm text-secondary">Waiting for first signal</span>
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1.5 min-h-5 min-w-0">
            <StatusDot color="bg-muted-alt" />
            <span className="text-sm text-secondary">Not collecting data yet</span>
        </span>
    )
}
