import { IconInfo } from '@posthog/icons'
import { LemonCard, Link, Tooltip } from '@posthog/lemon-ui'

export function ModelViewSummary({
    downstreamCount,
    lineageUrl,
}: {
    downstreamCount: number
    lineageUrl: string
}): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className="!p-4 w-fit max-w-full self-start"
            data-attr="node-detail-view-summary"
        >
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">Runs on demand</span>
                    <Tooltip title="Materialize to store results and refresh them on a schedule.">
                        <span
                            tabIndex={0}
                            aria-label="About on-demand views"
                            className="flex text-secondary cursor-help"
                        >
                            <IconInfo />
                        </span>
                    </Tooltip>
                </div>
                <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">
                    <div>
                        <dt className="text-secondary mb-1">
                            <Tooltip title="Models that depend on this model's results. Open lineage to see how they are connected.">
                                <span className="border-b border-dashed border-secondary cursor-help">Downstream</span>
                            </Tooltip>
                        </dt>
                        <dd className="mb-0">
                            {downstreamCount ? (
                                <Link to={lineageUrl}>
                                    <span>{`${downstreamCount} ${downstreamCount === 1 ? 'model' : 'models'}`}</span>
                                </Link>
                            ) : (
                                'No dependent models'
                            )}
                        </dd>
                    </div>
                </dl>
            </div>
        </LemonCard>
    )
}
