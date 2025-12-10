import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { ProductTourStats } from '../productTourLogic'

interface StatCardProps {
    title: string
    value: string | number
    subValue?: string
    description?: string
    loading?: boolean
}

function StatCard({ title, value, subValue, description, loading }: StatCardProps): JSX.Element {
    return (
        <div className="flex flex-col p-4 border rounded bg-surface-primary">
            <div className="text-secondary text-sm font-medium">{title}</div>
            {loading ? (
                <LemonSkeleton className="h-8 w-20 my-1" />
            ) : (
                <div className="flex items-baseline gap-2">
                    <div className="text-2xl font-bold">{value}</div>
                    {subValue && <div className="text-secondary text-sm">({subValue})</div>}
                </div>
            )}
            {description && <div className="text-secondary text-xs">{description}</div>}
        </div>
    )
}

interface ProductTourStatsSummaryProps {
    stats: ProductTourStats | null
    loading: boolean
    headerAction?: React.ReactNode
}

export function ProductTourStatsSummary({ stats, loading, headerAction }: ProductTourStatsSummaryProps): JSX.Element {
    const uniqueShown = stats?.uniqueShown ?? 0
    const uniqueCompleted = stats?.uniqueCompleted ?? 0
    const uniqueDismissed = stats?.uniqueDismissed ?? 0
    const totalShown = stats?.totalShown ?? 0
    const totalCompleted = stats?.totalCompleted ?? 0
    const totalDismissed = stats?.totalDismissed ?? 0

    const completionRate = uniqueShown > 0 ? Math.round((uniqueCompleted / uniqueShown) * 100) : 0
    const dismissalRate = uniqueShown > 0 ? Math.round((uniqueDismissed / uniqueShown) * 100) : 0

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Tour performance</h3>
                {headerAction}
            </div>
            <div className="grid grid-cols-3 gap-4">
                <StatCard
                    title="Unique users shown"
                    value={uniqueShown.toLocaleString()}
                    subValue={`${totalShown.toLocaleString()} total`}
                    description="Users who saw the tour"
                    loading={loading}
                />
                <StatCard
                    title="Completions"
                    value={uniqueCompleted.toLocaleString()}
                    subValue={`${totalCompleted.toLocaleString()} total`}
                    description={`${completionRate}% completion rate`}
                    loading={loading}
                />
                <StatCard
                    title="Dismissals"
                    value={uniqueDismissed.toLocaleString()}
                    subValue={`${totalDismissed.toLocaleString()} total`}
                    description={`${dismissalRate}% dismissal rate`}
                    loading={loading}
                />
            </div>
        </div>
    )
}
