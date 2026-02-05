import { useValues } from 'kea'

import { IconFlag, IconStar } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'
import { userLogic } from 'scenes/userLogic'

export function SavedInsightsFilters({
    filters,
    setFilters,
    showQuickFilters = true,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    showQuickFilters?: boolean
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { search, hideFeatureFlagInsights, createdBy, favorited } = filters

    return (
        <div className={cn('flex justify-between gap-2 items-center flex-wrap')}>
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setFilters({ search: value })}
                value={search || ''}
                autoFocus
            />
            <div className="flex items-center gap-2 flex-wrap">
                {showQuickFilters && (
                    <>
                        <LemonButton
                            type="secondary"
                            active={!!(user && createdBy !== 'All users' && (createdBy as number[]).includes(user.id))}
                            onClick={() => {
                                if (user) {
                                    const currentUsers = createdBy !== 'All users' ? (createdBy as number[]) : []
                                    const selected = new Set(currentUsers)
                                    if (selected.has(user.id)) {
                                        selected.delete(user.id)
                                    } else {
                                        selected.add(user.id)
                                    }
                                    const newValue = Array.from(selected)
                                    setFilters({ createdBy: newValue.length > 0 ? newValue : 'All users' })
                                }
                            }}
                            size="small"
                        >
                            Created by me
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            active={favorited || false}
                            onClick={() => setFilters({ favorited: !favorited })}
                            size="small"
                            icon={<IconStar />}
                        >
                            Favorites
                        </LemonButton>
                        <FeatureFlagInsightsToggle
                            hideFeatureFlagInsights={hideFeatureFlagInsights ?? undefined}
                            onToggle={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                        />
                    </>
                )}
            </div>
        </div>
    )
}

const FeatureFlagInsightsToggle = ({
    hideFeatureFlagInsights,
    onToggle,
}: {
    hideFeatureFlagInsights?: boolean
    onToggle: (checked: boolean) => void
}): JSX.Element => {
    return (
        <Tooltip
            title={
                <div>
                    <p>
                        PostHog automatically creates insights by default for feature flags to help you understand their
                        performance.
                    </p>
                    <p className="mb-0">
                        Use this toggle to hide these auto-generated insights from your insights list.
                    </p>
                </div>
            }
            placement="top"
        >
            <LemonButton
                icon={<IconFlag />}
                onClick={() => onToggle(!hideFeatureFlagInsights)}
                type="tertiary"
                size="small"
            >
                Hide feature flag insights: <LemonSwitch checked={hideFeatureFlagInsights || false} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
