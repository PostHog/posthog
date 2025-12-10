import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

interface ProductTourStats {
    shown: number
    completed: number
    dismissed: number
    stepStats: Array<{
        stepOrder: number
        shown: number
        completed: number
    }>
}

interface StatCardProps {
    title: string
    value: string | number
    description?: string
    loading?: boolean
}

function StatCard({ title, value, description, loading }: StatCardProps): JSX.Element {
    return (
        <div className="flex flex-col p-4 border rounded bg-surface-primary">
            <div className="text-secondary text-sm font-medium">{title}</div>
            {loading ? <LemonSkeleton className="h-8 w-20 my-1" /> : <div className="text-2xl font-bold">{value}</div>}
            {description && <div className="text-secondary text-xs">{description}</div>}
        </div>
    )
}

interface ProductTourStatsSummaryProps {
    stats: ProductTourStats | null
    loading: boolean
}

export function ProductTourStatsSummary({ stats, loading }: ProductTourStatsSummaryProps): JSX.Element {
    const shown = stats?.shown ?? 0
    const completed = stats?.completed ?? 0
    const dismissed = stats?.dismissed ?? 0

    const completionRate = shown > 0 ? Math.round((completed / shown) * 100) : 0
    const dismissalRate = shown > 0 ? Math.round((dismissed / shown) * 100) : 0

    return (
        <div>
            <h3 className="font-semibold mb-4">Tour performance</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard
                    title="Impressions"
                    value={shown.toLocaleString()}
                    description="Times the tour was shown"
                    loading={loading}
                />
                <StatCard
                    title="Completions"
                    value={completed.toLocaleString()}
                    description={`${completionRate}% completion rate`}
                    loading={loading}
                />
                <StatCard
                    title="Dismissals"
                    value={dismissed.toLocaleString()}
                    description={`${dismissalRate}% dismissal rate`}
                    loading={loading}
                />
                <StatCard
                    title="Completion rate"
                    value={`${completionRate}%`}
                    description="Users who finished all steps"
                    loading={loading}
                />
            </div>
        </div>
    )
}
