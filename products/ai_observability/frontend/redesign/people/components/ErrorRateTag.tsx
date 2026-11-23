import { LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

// At this share of generations ending in an error, the rate shows as a danger tag.
const HIGH_ERROR_RATE = 0.1

export function ErrorRateTag({ errors, total }: { errors: number; total: number }): JSX.Element {
    if (errors === 0 || total === 0) {
        return <span className="text-secondary tabular-nums">0</span>
    }
    const rate = errors / total
    return (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap tabular-nums">
            {humanFriendlyNumber(errors)}
            <LemonTag type={rate >= HIGH_ERROR_RATE ? 'danger' : 'warning'} size="small">
                {percentage(rate, 0)}
            </LemonTag>
        </span>
    )
}
