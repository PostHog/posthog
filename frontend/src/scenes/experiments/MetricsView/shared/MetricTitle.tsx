import { Tooltip } from '@posthog/lemon-ui'

import { ExperimentMetric } from '~/queries/schema/schema-general'

import { getDefaultMetricTitle } from './utils'

export const MetricTitle = ({ metric }: { metric: ExperimentMetric }): JSX.Element => {
    const title = metric.name || getDefaultMetricTitle(metric)
    // Use break-words for text with spaces, break-all for underscore-separated text
    const breakClass = title.includes(' ') ? 'break-words' : 'break-all'
    const element = <span className={`line-clamp-3 ${breakClass}`}>{title}</span>

    // Show tooltip for longer text that might be clamped
    return title.length > 50 ? <Tooltip title={title}>{element}</Tooltip> : element
}
