import { LemonButton, LemonMenu, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

export interface ClusterChipItem {
    label: string
    description: string | null
    jobName: string | null
    isOutlier: boolean
    runAt: string
    href: string
}

export interface TraceClustersChipProps {
    first: ClusterChipItem
    others: ClusterChipItem[]
}

function ClusterTooltip({ item }: { item: ClusterChipItem }): JSX.Element {
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

export function TraceClustersChip({ first, others }: TraceClustersChipProps): JSX.Element {
    return (
        <span className="inline-flex max-w-full min-w-0 items-center gap-1">
            <Tooltip title={<ClusterTooltip item={first} />}>
                <Link to={first.href} subtle className="min-w-0" data-attr="trace-view-cluster-chip">
                    <LemonTag weight="normal" type={first.isOutlier ? 'caution' : 'default'} className="max-w-full">
                        <span className="shrink-0">Cluster:&nbsp;</span>
                        <span className="max-w-60 truncate">{first.label}</span>
                    </LemonTag>
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
                                to: item.href,
                                'data-attr': 'trace-view-cluster-chip-item',
                            })),
                        },
                    ]}
                >
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        aria-label={`${others.length} more ${others.length === 1 ? 'cluster' : 'clusters'}`}
                        data-attr="trace-view-cluster-chip-more"
                    >
                        {`+${others.length}`}
                    </LemonButton>
                </LemonMenu>
            ) : null}
        </span>
    )
}
