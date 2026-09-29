import { LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

export function ModelDownstreamSummary({
    downstreamCount,
    lineageUrl,
    loading = false,
}: {
    downstreamCount: number
    lineageUrl: string
    loading?: boolean
}): JSX.Element {
    return (
        <div>
            <dt className="text-secondary mb-1">
                <Tooltip title="Models that depend on this model's results. Open lineage to see how they are connected.">
                    <span className="border-b border-dashed border-secondary cursor-help">Downstream</span>
                </Tooltip>
            </dt>
            <dd className="mb-0">
                {loading ? (
                    <LemonSkeleton className="h-4 w-32" />
                ) : downstreamCount ? (
                    <Link to={lineageUrl}>
                        <span>{`${downstreamCount} ${downstreamCount === 1 ? 'model' : 'models'}`}</span>
                    </Link>
                ) : (
                    'No dependent models'
                )}
            </dd>
        </div>
    )
}
