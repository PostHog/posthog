import { useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { resultsBreakdownLogic } from './resultsBreakdownLogic'

export function ExploreAsInsightButton({
    experiment,
    result,
}: {
    experiment: Experiment
    result: CachedExperimentQueryResponse
}): JSX.Element | null {
    const { query } = useValues(resultsBreakdownLogic({ experiment, metric: result.metric }))

    if (!result || !query) {
        return null
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size="xsmall"
            type="primary"
            icon={<IconAreaChart />}
            to={urls.insightNew({ query })}
            targetBlank
        >
            Explore as Insight
        </LemonButton>
    )
}
