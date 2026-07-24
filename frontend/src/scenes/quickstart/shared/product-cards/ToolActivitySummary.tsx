import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { QuickstartProduct, QuickstartToolStatus } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'

export function ToolActivitySummary({
    product,
    status,
    installationInProgress,
}: {
    product: QuickstartProduct
    status: QuickstartToolStatus
    installationInProgress: boolean
}): JSX.Element {
    if (installationInProgress) {
        return (
            <div className="flex items-center gap-1.5 min-h-5 min-w-0" data-attr="quickstart-product-installing">
                <span className="relative flex items-center justify-center size-2">
                    <span className="absolute size-2 rounded-full bg-accent opacity-25 animate-pulse" />
                    <span className="relative size-1.5 rounded-full bg-accent" />
                </span>
                <span className="text-sm text-secondary">Installing the PostHog SDK</span>
            </div>
        )
    }
    if (status.stat) {
        return (
            <div className="flex items-baseline gap-1.5 min-h-5 min-w-0">
                <span className="size-1.5 rounded-full bg-success shrink-0" />
                <Link
                    to={product.url}
                    onClick={() => captureQuickstartAction('view_tool_activity', product.key)}
                    className="inline-flex items-baseline gap-1 min-w-0"
                    data-attr={`quickstart-activity-${product.key}`}
                >
                    <span className="text-sm font-semibold tabular-nums text-primary">
                        {humanFriendlyLargeNumber(status.stat.value)}
                    </span>
                    <span className="text-sm text-secondary truncate">{status.stat.label}</span>
                </Link>
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
