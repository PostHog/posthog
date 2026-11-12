import { LemonMenu, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { TraceClusterApi } from '../../../generated/api.schemas'
import { ChipButton } from './ChipButton'
import { ChipTag } from './ChipTag'
import { LabeledChipValue } from './LabeledChipValue'

export interface TraceClustersChipProps {
    clusters: TraceClusterApi[]
}

function clusterHref(cluster: TraceClusterApi): string {
    return urls.aiObservabilityCluster(cluster.runId, cluster.clusterId)
}

function ClusterTooltip({ item }: { item: TraceClusterApi }): JSX.Element {
    return (
        <div className="flex max-w-80 flex-col gap-1">
            <span className="font-semibold">{item.label}</span>
            {item.description ? <span>{item.description}</span> : null}
            {item.isOutlier ? <span>This trace didn't fit any cluster in this run.</span> : null}
            {item.jobName ? <span className="opacity-75">From {item.jobName}</span> : null}
            <span className="opacity-75">Run {dayjs(item.runAt).fromNow()}</span>
        </div>
    )
}

export function TraceClustersChip({ clusters }: TraceClustersChipProps): JSX.Element | null {
    const [first, ...others] = clusters
    if (!first) {
        return null
    }
    return (
        <span className="inline-flex max-w-full min-w-0 items-center gap-1.5">
            <Tooltip title={<ClusterTooltip item={first} />}>
                <Link
                    to={clusterHref(first)}
                    subtle
                    className="inline-flex min-w-0"
                    data-attr="trace-view-cluster-chip"
                >
                    <ChipTag weight="normal" type={first.isOutlier ? 'caution' : 'default'} className="max-w-full">
                        <LabeledChipValue label="Cluster">{first.label}</LabeledChipValue>
                    </ChipTag>
                </Link>
            </Tooltip>
            {others.length > 0 ? (
                <LemonMenu
                    items={[
                        {
                            title: 'Also in',
                            items: others.map((item) => ({
                                label: (
                                    <span className="flex min-w-0 flex-col">
                                        <span className="flex items-center gap-1">
                                            <span className="truncate">{item.label}</span>
                                            {item.isOutlier ? (
                                                <LemonTag size="small" type="caution">
                                                    Outlier
                                                </LemonTag>
                                            ) : null}
                                        </span>
                                        {item.jobName ? (
                                            <span className="text-xs text-secondary">{item.jobName}</span>
                                        ) : null}
                                    </span>
                                ),
                                to: clusterHref(item),
                                'data-attr': 'trace-view-cluster-chip-item',
                            })),
                        },
                    ]}
                >
                    <ChipButton
                        aria-label={`${others.length} more ${others.length === 1 ? 'cluster' : 'clusters'}`}
                        data-attr="trace-view-cluster-chip-more"
                    >
                        {`+${others.length}`}
                    </ChipButton>
                </LemonMenu>
            ) : null}
        </span>
    )
}
