import { LemonTag } from '@posthog/lemon-ui'

import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { getMetricTag } from './utils'

export function MetricTypeTag({
    metric,
}: {
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
}): JSX.Element {
    return (
        <LemonTag type="muted" size="small">
            {getMetricTag(metric)}
        </LemonTag>
    )
}
