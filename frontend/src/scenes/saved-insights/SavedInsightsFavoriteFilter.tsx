import { IconHeart, IconHeartFilled } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

export function SavedInsightsFavoriteFilter({
    favorited,
    setFilters,
    borderless,
}: {
    favorited: boolean | undefined | null
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    borderless: boolean
}): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            status={borderless && !favorited ? 'alt' : 'default'}
            active={favorited || false}
            onClick={() => setFilters({ favorited: !favorited })}
            size="small"
            icon={favorited ? <IconHeartFilled className="text-danger" /> : <IconHeart className="text-secondary" />}
        >
            Favorites
        </LemonButton>
    )
}
