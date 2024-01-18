import { LemonCard, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { percentage } from 'lib/utils'
import { urls } from 'scenes/urls'

import { PipelineAppKind, PipelineAppTab } from '~/types'

import { DestinationMoreOverlay } from './Destinations'
import { DestinationType, PipelineAppBackend } from './destinationsLogic'
import { DestinationSparkLine } from './DestinationSparkLine'
import { pipelineOverviewLogic } from './overviewLogic'
import { pipelineAppMetricsLogic } from './pipelineAppMetricsLogic'
import { TransformationsMoreOverlay } from './Transformations'
import { humanFriendlyFrequencyName } from './utils'

const FAILURE_RATE_WARNING_THRESHOLD = 0
const FAILURE_RATE_ERROR_THRESHOLD = 0.03

type StatusMetrics = {
    totals: number
    failures: number
}

type StatusIndicatorProps = {
    enabled: boolean
    metrics?: StatusMetrics
}

const StatusMessage = ({ enabled, metrics }: StatusIndicatorProps): JSX.Element => {
    if (!enabled) {
        return <i>Disabled.</i>
    }

    if (!metrics) {
        return (
            <span>
                Enabled - <i>No events processed in the last 7 days.</i>
            </span>
        )
    }

    const failureRate = metrics.failures / metrics.totals

    if (metrics.failures > 0) {
        return (
            <span>
                {metrics.totals} events processed with {percentage(failureRate)} failures (a total of {metrics.failures}{' '}
                event(s)) in the last 7 days.
            </span>
        )
    }

    return <span>{metrics.totals} events processed without errors in the last 7 days.</span>
}

const StatusIndicator = ({ enabled, metrics }: StatusIndicatorProps): JSX.Element => {
    const failureRate = metrics ? metrics?.failures / metrics?.totals : null

    let statusColor: string = 'bg-success'
    if (failureRate && failureRate > FAILURE_RATE_ERROR_THRESHOLD) {
        statusColor = 'bg-danger'
    } else if (failureRate && failureRate > FAILURE_RATE_WARNING_THRESHOLD) {
        statusColor = 'bg-warning'
    }

    return (
        <Tooltip title={<StatusMessage enabled={enabled} metrics={metrics} />} placement="right">
            <div className="relative flex h-3 w-3 items-center justify-center">
                <span
                    className={clsx('absolute inline-flex h-3/4 w-3/4 rounded-full opacity-50', {
                        [`${statusColor} animate-ping`]: enabled,
                        'bg-border': !enabled,
                    })}
                />
                <span
                    className={clsx('relative inline-flex rounded-full h-3 w-3', {
                        [`${statusColor}`]: enabled,
                    })}
                />
            </div>
        </Tooltip>
    )
}

type PipelineStepProps = {
    order?: number
    enabled: boolean
    name: string
    to: string
    metrics?: StatusMetrics
    description?: string
    headerInfo: JSX.Element
    additionalInfo?: JSX.Element
}

const PipelineStep = ({
    order,
    enabled,
    name,
    to,
    metrics,
    description,
    headerInfo,
    additionalInfo,
}: PipelineStepProps): JSX.Element => (
    <LemonCard>
        {order && (
            <div className="mb-3">
                <SeriesGlyph
                    style={{
                        color: 'var(--muted)',
                        borderColor: 'var(--muted)',
                    }}
                >
                    {order}
                </SeriesGlyph>
            </div>
        )}

        <div className="flex items-center justify-between mb-3">
            <div className="flex items-center">
                <h3 className="mb-0 mr-2">
                    <Link to={to} subtle>
                        {name}
                    </Link>
                </h3>
                <StatusIndicator enabled={enabled} metrics={metrics} />
            </div>
            <div className="flex items-center">{headerInfo}</div>
        </div>

        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <span className="italic">No description.</span>
        )}

        {additionalInfo && <div className="mt-3 flex flex-end">{additionalInfo}</div>}
    </LemonCard>
)

const PipelineStepSkeleton = (): JSX.Element => (
    <LemonCard>
        <LemonSkeleton className="h-5 w-1/3 mb-3" />
        <LemonSkeleton className="h-4 w-3/4 mb-3" />
        <LemonSkeleton className="h-4 w-1/2" />
    </LemonCard>
)

type PipelineStepTransformationProps = {
    order?: number
    name: string
    description?: string
    enabled?: boolean
    to: string
    success_rate?: number
    moreOverlay?: JSX.Element
    sparkline?: JSX.Element
}

const PipelineStepTransformation = ({
    name,
    description,
    order,
    enabled,
    to,
    moreOverlay,
    sparkline,
}: PipelineStepTransformationProps): JSX.Element => (
    <LemonCard>
        {order && (
            <div className="mb-3">
                <SeriesGlyph
                    style={{
                        color: 'var(--muted)',
                        borderColor: 'var(--muted)',
                    }}
                >
                    {order}
                </SeriesGlyph>
            </div>
        )}

        <div className="flex items-center justify-between mb-3">
            <div className="flex items-center">
                <h3 className="mb-0 mr-2">
                    <Link to={to} subtle>
                        {name}
                    </Link>
                </h3>
                <StatusIndicator status={enabled ? 'enabled' : 'disabled'} />
            </div>
            <div className="flex items-center">
                {sparkline && <div className="mr-1">{sparkline}</div>}
                {moreOverlay && <More overlay={moreOverlay} />}
            </div>
        </div>

        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <span className="italic">No description.</span>
        )}

        <div className="mt-3 flex flex-end">
            {enabled !== undefined && (
                <>
                    {enabled ? (
                        <LemonTag type="success" className="uppercase">
                            Enabled
                        </LemonTag>
                    ) : (
                        <LemonTag type="default" className="uppercase">
                            Disabled
                        </LemonTag>
                    )}
                </>
            )}
        </div>
    </LemonCard>
)

const PipelineStepDestination = ({ destination }: { destination: DestinationType }): JSX.Element => {
    let metrics: StatusMetrics | undefined = undefined
    if (destination.backend !== PipelineAppBackend.BatchExport) {
        const logic = pipelineAppMetricsLogic({ pluginConfigId: destination.id })
        const { appMetricsResponse } = useValues(logic)

        if (appMetricsResponse) {
            metrics = {
                totals: appMetricsResponse.metrics.totals.successes + appMetricsResponse.metrics.totals.failures,
                failures: appMetricsResponse.metrics.totals.failures,
            }
        }
    }

    return (
        <PipelineStep
            name={destination.name}
            to={destination.config_url}
            description={destination.description}
            enabled={destination.enabled}
            metrics={metrics}
            headerInfo={
                <>
                    <DestinationSparkLine destination={destination} />
                    <More overlay={<DestinationMoreOverlay destination={destination} />} />
                </>
            }
            additionalInfo={
                <div className="flex gap-1">
                    {destination.backend === PipelineAppBackend.Plugin ? (
                        <LemonTag type="primary">Plugin</LemonTag>
                    ) : (
                        <LemonTag type="primary">
                            {humanFriendlyFrequencyName(destination.frequency)} Batch Export
                        </LemonTag>
                    )}
                    {destination.backend === PipelineAppBackend.BatchExport}
                </div>
            }
        />
    )
}

export function Overview(): JSX.Element {
    const { transformations, destinations, transformationsLoading, destinationsLoading } =
        useValues(pipelineOverviewLogic)

    return (
        <div>
            <h2>Filters</h2>
            <p>
                <i>Coming soon.</i>
            </p>

            <h2 className="mt-4">Transformations</h2>
            <div className="grid grid-cols-3 gap-4">
                {transformationsLoading && <PipelineStepSkeleton />}
                {transformations &&
                    transformations.map((t) => (
                        <PipelineStepTransformation
                            key={t.id}
                            name={t.name}
                            description={t.description}
                            order={1} // TODO
                            // enabled={} // TODO
                            to={urls.pipelineApp(PipelineAppKind.Transformation, t.id, PipelineAppTab.Configuration)}
                            moreOverlay={<TransformationsMoreOverlay pluginConfig={{}} />}
                        />
                    ))}
            </div>
            {/* {transformations && <pre>{JSON.stringify(transformations, null, 2)}</pre>} */}

            <h2 className="mt-4">Destinations</h2>
            <div className="grid grid-cols-3 gap-4">
                {destinationsLoading && <PipelineStepSkeleton />}
                {destinations && destinations.map((d) => <PipelineStepDestination key={d.id} destination={d} />)}
            </div>
            {/* {destinations && <pre>{JSON.stringify(destinations, null, 2)}</pre>} */}
        </div>
    )
}
