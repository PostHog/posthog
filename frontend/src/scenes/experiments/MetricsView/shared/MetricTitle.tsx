import { IconArrowRight, IconFunnels } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { getDefaultMetricTitle } from './utils'

export const MetricTitle = ({ metric, metricType }: { metric: any; metricType?: InsightType }): JSX.Element => {
    const getTextClassName = (text: string): string => {
        // If text contains spaces, allow word breaks; otherwise truncate
        return text.includes(' ') ? 'break-words' : 'truncate'
    }

    const shouldShowTooltip = (text: string): boolean => {
        // Only show tooltip when we're truncating (single long words without spaces)
        return !text.includes(' ') && text.length > 15
    }

    const wrapWithTooltip = (text: string, element: JSX.Element): JSX.Element => {
        if (shouldShowTooltip(text)) {
            return <Tooltip title={text}>{element}</Tooltip>
        }
        return element
    }

    if (metric.name) {
        const element = <span className={getTextClassName(metric.name)}>{metric.name}</span>
        return wrapWithTooltip(metric.name, element)
    }

    if (metric.kind === NodeKind.ExperimentMetric) {
        const title = getDefaultMetricTitle(metric)
        const element = <span className={getTextClassName(title)}>{title}</span>
        return wrapWithTooltip(title, element)
    }

    if (metricType === InsightType.TRENDS && metric.count_query?.series?.[0]?.name) {
        const name = metric.count_query.series[0].name
        const element = <span className={getTextClassName(name)}>{name}</span>
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
                        {wrapWithTooltip(firstStep, <span className={getTextClassName(firstStep)}>{firstStep}</span>)}
                    </div>
                    <div className="inline-flex items-center gap-1 min-w-0 @max-[200px]:ml-5">
                        <IconArrowRight className="text-secondary flex-shrink-0" fontSize="14" />
                        {wrapWithTooltip(lastStep, <span className={getTextClassName(lastStep)}>{lastStep}</span>)}
                    </div>
                </div>
            )
        }
    }

    return <span className="text-secondary break-words">Untitled metric</span>
}
