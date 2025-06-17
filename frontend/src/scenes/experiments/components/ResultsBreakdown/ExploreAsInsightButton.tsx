import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import type { ResultBreakdownRenderProps } from './types'

/**
 * make the props non-nullable
 */
type SafeResultBreakdownRenderProps = {
    [K in keyof Pick<ResultBreakdownRenderProps, 'query'>]: NonNullable<ResultBreakdownRenderProps[K]>
}

export function ExploreAsInsightButton({ query }: SafeResultBreakdownRenderProps): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENTS_NEW_RUNNER_RESULTS_BREAKDOWN')

    if (!isEnabled) {
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
