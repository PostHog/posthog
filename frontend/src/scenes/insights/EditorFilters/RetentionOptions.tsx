import { Link } from '@posthog/lemon-ui'

import { RetentionCumulativeButton } from '../filters/RetentionCumulativeButton'
import { RetentionReferencePicker } from '../filters/RetentionReferencePicker'

export function RetentionOptions(): JSX.Element {
    return (
        <div className="space-y-3" data-attr="retention-options">
            <div className="flex items-center gap-2">
                <div>Retention relative to</div>
                <RetentionReferencePicker />
            </div>
            <div className="flex items-center gap-2">
                <div>When users return</div>
                <RetentionCumulativeButton />
                <div>the period</div>
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
