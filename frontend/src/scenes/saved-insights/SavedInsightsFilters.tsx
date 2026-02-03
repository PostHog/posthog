import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFlag, IconStar } from '@posthog/icons'
import { LemonSelectOption, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { tagSelectLogic } from 'lib/components/tagSelectLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
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
    const { search, hideFeatureFlagInsights, createdBy, favorited, tags, insightType } = filters

    const { filteredTags, search: tagSearch } = useValues(tagSelectLogic)
    const { setSearch: setTagSearch } = useActions(tagSelectLogic)

    const handleTagToggle = (tag: string): void => {
        const selected = new Set(tags || [])
        if (selected.has(tag)) {
            selected.delete(tag)
        } else {
            selected.add(tag)
        }
        setFilters({ tags: Array.from(selected) })
    }

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
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    actionable: true,
                                    overlay: (
                                        <div className="deprecated-space-y-px">
                                            {(INSIGHT_TYPE_OPTIONS as LemonSelectOption<string>[]).map((option) => {
                                                const opt = option as LemonSelectOptionLeaf<string>
                                                return (
                                                    <LemonButton
                                                        key={opt.value}
                                                        onClick={() =>
                                                            setFilters({
                                                                insightType: opt.value,
                                                            })
                                                        }
                                                        active={insightType === opt.value}
                                                        icon={opt.icon}
                                                        fullWidth
                                                    >
                                                        {opt.label}
                                                    </LemonButton>
                                                )
                                            })}
                                            {insightType && insightType !== 'All types' && (
                                                <>
                                                    <div className="my-1 border-t" />
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => setFilters({ insightType: 'All types' })}
                                                        type="tertiary"
                                                    >
                                                        Clear filter
                                                    </LemonButton>
                                                </>
                                            )}
                                        </div>
                                    ),
                                },
                                icon: <IconChevronDown />,
                            }}
                            active={insightType !== 'All types'}
                            size="small"
                        >
                            {(
                                INSIGHT_TYPE_OPTIONS.find((o) => 'value' in o && o.value === insightType) as
                                    | LemonSelectOptionLeaf<string>
                                    | undefined
                            )?.label || 'All types'}
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    actionable: true,
                                    overlay: (
                                        <div className="max-w-100 deprecated-space-y-2">
                                            <LemonInput
                                                type="search"
                                                placeholder="Search tags"
                                                autoFocus
                                                value={tagSearch}
                                                onChange={setTagSearch}
                                                fullWidth
                                                className="max-w-full"
                                            />
                                            <ul className="deprecated-space-y-px">
                                                {filteredTags.map((tag: string) => (
                                                    <li key={tag}>
                                                        <LemonButton
                                                            fullWidth
                                                            role="menuitem"
                                                            size="small"
                                                            onClick={() => handleTagToggle(tag)}
                                                        >
                                                            <span className="flex items-center justify-between gap-2 flex-1">
                                                                <span className="flex items-center gap-2 max-w-full">
                                                                    <input
                                                                        type="checkbox"
                                                                        className="cursor-pointer"
                                                                        checked={tags?.includes(tag) || false}
                                                                        readOnly
                                                                    />
                                                                    <span>{tag}</span>
                                                                </span>
                                                            </span>
                                                        </LemonButton>
                                                    </li>
                                                ))}
                                                {filteredTags.length === 0 ? (
                                                    <div className="p-2 text-secondary italic truncate border-t">
                                                        {tagSearch ? (
                                                            <span>No matching tags</span>
                                                        ) : (
                                                            <span>No tags</span>
                                                        )}
                                                    </div>
                                                ) : null}
                                                {(tags?.length || 0) > 0 && (
                                                    <>
                                                        <div className="my-1 border-t" />
                                                        <li>
                                                            <LemonButton
                                                                fullWidth
                                                                role="menuitem"
                                                                size="small"
                                                                onClick={() => setFilters({ tags: [] })}
                                                                type="tertiary"
                                                            >
                                                                Clear selection
                                                            </LemonButton>
                                                        </li>
                                                    </>
                                                )}
                                            </ul>
                                        </div>
                                    ),
                                },
                                icon: <IconChevronDown />,
                            }}
                            active={(tags?.length || 0) > 0}
                            size="small"
                        >
                            Tags{(tags?.length || 0) > 0 ? `: ${tags?.length}` : ''}
                        </LemonButton>

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
                    </>
                )}
                <FeatureFlagInsightsToggle
                    hideFeatureFlagInsights={hideFeatureFlagInsights ?? undefined}
                    onToggle={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                />
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
