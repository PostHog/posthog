import { IconArrowRight, IconFunnels } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { getDefaultMetricTitle } from './utils'

export const MetricTitle = ({ metric, metricType }: { metric: any; metricType?: InsightType }): JSX.Element => {
    const shouldShowTooltip = (text: string): boolean => {
        // Show tooltip for longer text that might be clamped
        return text.length > 50
    }

    const wrapWithTooltip = (text: string, element: JSX.Element): JSX.Element => {
        if (shouldShowTooltip(text)) {
            return <Tooltip title={text}>{element}</Tooltip>
        }
        return element
    }

    if (metric.kind === NodeKind.ExperimentMetric) {
        const title = metric.name || getDefaultMetricTitle(metric)
        const element = <span className="line-clamp-3">{title}</span>
        return wrapWithTooltip(title, element)
    }

    if (metricType === InsightType.TRENDS && metric.count_query?.series?.[0]?.name) {
        const name = metric.count_query.series[0].name
        const element = <span className="line-clamp-3">{name}</span>
        return wrapWithTooltip(name, element)
    }

    if (metricType === InsightType.FUNNELS && metric.funnels_query?.series) {
        const series = metric.funnels_query.series
        if (series.length > 0) {
            const firstStep = series[0]?.name
            const lastStep = series[series.length - 1]?.name

            return (
                <div className="inline-flex flex-wrap items-center gap-1 min-w-0">
                    <div className="inline-flex items-center gap-1 min-w-0">
                        <IconFunnels className="text-secondary flex-shrink-0" fontSize="14" />
                        {wrapWithTooltip(firstStep, <span className="line-clamp-3">{firstStep}</span>)}
                    </div>
                    <div className="inline-flex items-center gap-1 min-w-0 @max-[200px]:ml-5">
                        <IconArrowRight className="text-secondary flex-shrink-0" fontSize="14" />
                        {wrapWithTooltip(lastStep, <span className="line-clamp-3">{lastStep}</span>)}
                    </div>
                </div>
            )
        }
    }

    return <span className="text-secondary line-clamp-3">Untitled metric</span>
}
