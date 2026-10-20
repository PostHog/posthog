import { Tooltip } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'

import { getDefaultMetricTitle } from './utils'

export const MetricTitle = ({ metric, singleLine }: { metric: any; singleLine?: boolean }): JSX.Element => {
    const shouldShowTooltip = (text: string): boolean => {
        // Show tooltip for longer text that might be clamped
        return text.length > 50
    }

    const getTextClassName = (text: string): string => {
        if (singleLine) {
            return 'truncate block'
        }
        // Use break-words for text with spaces, break-all for underscore-separated text
        const breakClass = text.includes(' ') ? 'break-words' : 'break-all'
        return `line-clamp-3 ${breakClass}`
    }

    const wrapWithTooltip = (text: string, element: JSX.Element): JSX.Element => {
        if (shouldShowTooltip(text)) {
            return <Tooltip title={text}>{element}</Tooltip>
        }
        return element
    }

    if (metric.kind === NodeKind.ExperimentMetric) {
        const title = metric.name || getDefaultMetricTitle(metric)
        const element = <span className={getTextClassName(title)}>{title}</span>
        return wrapWithTooltip(title, element)
    }

    return <span className={`text-secondary ${getTextClassName('Untitled metric')}`}>Untitled metric</span>
}
