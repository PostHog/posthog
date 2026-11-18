import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'

import { EndpointTimeSpentLogicProps, endpointTimeSpentLogic } from './endpointTimeSpentLogic'
import type { TimeSpentComponentApi } from './generated/api.schemas'
import { formatMs, formatPercent } from './healthDisplay'

const KIND_LABELS: Record<TimeSpentComponentApi['kind'], string> = {
    service: 'Service',
    inferred: 'Inferred',
    other: 'Other',
}

export function EndpointTimeSpent(props: EndpointTimeSpentLogicProps): JSX.Element {
    const { timeSpent, timeSpentLoading, timeSpentFailed } = useValues(endpointTimeSpentLogic(props))

    if (timeSpentLoading && !timeSpent) {
        return <LemonSkeleton className="h-24" />
    }
    if (!timeSpent) {
        return (
            <LemonBanner type="error">
                Couldn't load where this endpoint spends its time. Try again shortly.
            </LemonBanner>
        )
    }
    if (timeSpent.components.length === 0) {
        return <div className="text-muted text-sm p-2">No sampled requests for this endpoint in this time range.</div>
    }

    const colored = timeSpent.components.map((component, index) => ({ ...component, color: getSeriesColor(index) }))

    return (
        <div className="flex flex-col gap-2 p-2" data-attr="apm-endpoint-time-spent">
            <div className="flex items-baseline gap-2">
                <span className="font-semibold">Where time is spent</span>
                <span className="text-muted text-xs">
                    From {timeSpent.request_count} sampled {timeSpent.request_count === 1 ? 'request' : 'requests'},
                    averaging {formatMs(timeSpent.avg_duration_ms)}
                </span>
            </div>
            <span className="text-muted text-xs">
                Shares of total work across all calls. Parallel calls each count in full, so shares can differ from
                wall-clock time.
            </span>
            {timeSpentFailed && (
                <LemonBanner type="warning">Couldn't refresh this breakdown. It shows the last one loaded.</LemonBanner>
            )}
            <div className="flex h-4 w-full overflow-hidden rounded">
                {colored.map((component) => (
                    <Tooltip
                        key={`${component.kind}:${component.name}`}
                        title={`${component.name}: ${formatPercent(component.share)}`}
                    >
                        <div
                            className="h-full"
                            // Segment widths and colors are data, so they can't be utility classes.
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${component.share * 100}%`, backgroundColor: component.color }}
                        />
                    </Tooltip>
                ))}
            </div>
            <LemonTable
                size="small"
                dataSource={colored}
                rowKey={(row) => `${row.kind}:${row.name}`}
                columns={[
                    {
                        title: 'Service or dependency',
                        key: 'name',
                        render: (_, row) => (
                            <span className="flex items-center gap-2">
                                <span
                                    className="inline-block size-2 rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: row.color }}
                                />
                                {row.name}
                            </span>
                        ),
                    },
                    {
                        title: 'Type',
                        key: 'kind',
                        render: (_, row) => <LemonTag type="muted">{KIND_LABELS[row.kind]}</LemonTag>,
                    },
                    {
                        title: 'Avg per request',
                        key: 'avg_ms_per_request',
                        align: 'right',
                        render: (_, row) => <span className="font-mono">{formatMs(row.avg_ms_per_request)}</span>,
                    },
                    {
                        title: 'Share',
                        key: 'share',
                        align: 'right',
                        render: (_, row) => <span className="font-mono">{formatPercent(row.share)}</span>,
                    },
                ]}
            />
        </div>
    )
}
