import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from 'scenes/retention/retentionLogic'

import { MinimumOccurrencesInput } from '../filters/MinimumOccurrencesInput'
import { RetentionAggregationSelector } from '../filters/RetentionAggregationSelector'
import { RetentionCumulativeButton } from '../filters/RetentionCumulativeButton'
import { RetentionMeanDropdown } from '../filters/RetentionMeanDropdown'
import { RetentionReferencePicker } from '../filters/RetentionReferencePicker'
import { RetentionTimeWindowModePicker } from '../filters/RetentionTimeWindowModePicker'

export function RetentionOptions(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const { minimumOccurrences = 1, aggregationType } = retentionFilter || {}

    return (
        <div className="deprecated-space-y-3" data-attr="retention-options">
            {featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_RETENTION_AGGREGATION] && (
                <div className="flex items-center gap-2">
                    <div>Calculate</div>
                    <RetentionAggregationSelector />
                </div>
            )}
            {(!aggregationType || aggregationType === 'count') && (
                <>
                    <div className="flex items-center gap-2">
                        <div>Retention relative to</div>
                        <RetentionReferencePicker />
                    </div>
                    <div className="flex items-center gap-2">
                        <div>When users return</div>
                        <RetentionCumulativeButton />
                        <div>the interval</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <div>When users return at least</div>
                        <MinimumOccurrencesInput />
                        <div>{pluralize(minimumOccurrences, 'time', 'times', false)} in an interval</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <div>Mean calculation logic</div>
                        <RetentionMeanDropdown />
                    </div>
                    <div className="flex items-center gap-2">
                        <div>Time window</div>
                        <RetentionTimeWindowModePicker />
                    </div>
                </>
            )}

            <div>
                <p className="text-secondary mt-4">
                    <Link
                        to="https://posthog.com/docs/product-analytics/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product"
                        target="_blank"
                        className="inline-flex items-center"
                    >
                        Learn more in docs
                    </Link>
                </p>
            </div>
        </div>
    )
}
