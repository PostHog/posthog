import { LemonButton } from '@posthog/lemon-ui'

import { IconAreaChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { type ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { getInsightVizNodeQuery } from '../utils'

export function ExperimentMetricExploreInsightButton({
    experiment,
    metric,
    variantKey,
}: {
    experiment: Experiment
    metric: ExperimentMetric
    variantKey: string
}): JSX.Element {
    if (!metric) {
        return <></>
    }

    const query = getInsightVizNodeQuery(experiment, metric, variantKey)

    if (query == null) {
        return <></>
    }

    return (
        <LemonButton type="secondary" size="xsmall" icon={<IconAreaChart />} to={urls.insightNew({ query })}>
            Explore as Insight
        </LemonButton>
    )
}
