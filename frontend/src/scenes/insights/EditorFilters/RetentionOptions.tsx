import { Link } from '@posthog/lemon-ui'

import { RetentionCumulativeButton } from '../filters/RetentionCumulativeButton'
import { RetentionMeanDropdown } from '../filters/RetentionMeanDropdown'
import { RetentionReferencePicker } from '../filters/RetentionReferencePicker'
import { MinimumOccurrencesInput } from '../filters/MinimumOccurrencesInput'
import { retentionLogic } from 'scenes/retention/retentionLogic'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

export function RetentionOptions(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))
    const { minimumOccurrences = 1 } = retentionFilter || {}

    return (
        <div className="deprecated-space-y-3" data-attr="retention-options">
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
                <div>time{minimumOccurrences === 1 ? '' : 's'} in an interval</div>
            </div>
            <div className="flex items-center gap-2">
                <div>Mean calculation logic</div>
                <RetentionMeanDropdown />
            </div>
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
