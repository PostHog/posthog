import { useActions, useValues } from 'kea'

import { IconFlag, IconStar } from '@posthog/icons'
import { LemonDropdown, ProfilePicture } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { fullName } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { membersLogic } from 'scenes/organization/membersLogic'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

export function SavedInsightsFilters({
    filters,
    setFilters,
    showQuickFilters = true,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    showQuickFilters?: boolean
}): JSX.Element {
    const { search, hideFeatureFlagInsights, createdBy, favorited, tags, insightType } = filters

    const { meFirstMembers, filteredMembers, search: memberSearch } = useValues(membersLogic)
    const { setSearch: setMemberSearch, ensureAllMembersLoaded } = useActions(membersLogic)

    const handleMemberToggle = (userId: number): void => {
        const currentUsers = createdBy !== 'All users' ? (createdBy as number[]) : []
        const selected = new Set(currentUsers)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        const newValue = Array.from(selected)
        setFilters({ createdBy: newValue.length > 0 ? newValue : 'All users' })
    }

    return (
        <div className={cn('flex justify-between gap-2 items-center flex-wrap')}>
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setFilters({ search: value })}
                value={search || ''}
                autoFocus
                data-attr="insight-dashboard-modal-search"
            />
            <div className="flex items-center gap-2 flex-wrap">
                {showQuickFilters && (
                    <>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            onChange={(value) => {
                                setFilters({ insightType: value as string })
                            }}
                            options={INSIGHT_TYPE_OPTIONS}
                            value={insightType || 'All types'}
                        />
                        <TagSelect
                            value={tags || []}
                            onChange={(tags) => {
                                setFilters({ tags: tags.length > 0 ? tags : [] })
                            }}
                        >
                            {(selectedTags) => (
                                <LemonButton size="small" type="secondary">
                                    {selectedTags.length > 0 ? `Tags (${selectedTags.length})` : 'Tags'}
                                </LemonButton>
                            )}
                        </TagSelect>

                        <LemonDropdown
                            closeOnClickInside={false}
                            matchWidth={false}
                            placement="bottom-end"
                            actionable
                            overlay={
                                <div
                                    className="max-w-100 deprecated-space-y-2"
                                    onClick={() => ensureAllMembersLoaded()}
                                >
                                    <LemonInput
                                        type="search"
                                        placeholder="Search"
                                        autoFocus
                                        value={memberSearch}
                                        onChange={setMemberSearch}
                                        fullWidth
                                    />
                                    <ul className="deprecated-space-y-px">
                                        {filteredMembers.map((member) => (
                                            <li key={member.user.uuid}>
                                                <LemonButton
                                                    fullWidth
                                                    role="menuitem"
                                                    size="small"
                                                    icon={<ProfilePicture size="md" user={member.user} />}
                                                    onClick={() => handleMemberToggle(member.user.id)}
                                                >
                                                    <span className="flex items-center justify-between gap-2 flex-1">
                                                        <span className="flex items-center gap-2 max-w-full">
                                                            <input
                                                                type="checkbox"
                                                                className="cursor-pointer"
                                                                checked={
                                                                    createdBy !== 'All users' &&
                                                                    (createdBy as number[]).includes(member.user.id)
                                                                }
                                                                readOnly
                                                            />
                                                            <span>{fullName(member.user)}</span>
                                                        </span>
                                                        <span className="text-secondary">
                                                            {meFirstMembers[0] === member && `(you)`}
                                                        </span>
                                                    </span>
                                                </LemonButton>
                                            </li>
                                        ))}
                                        {filteredMembers.length === 0 ? (
                                            <div className="p-2 text-secondary italic truncate border-t">
                                                {memberSearch ? <span>No matches</span> : <span>No users</span>}
                                            </div>
                                        ) : null}
                                        {createdBy !== 'All users' && (createdBy as number[]).length > 0 && (
                                            <>
                                                <div className="my-1 border-t" />
                                                <li>
                                                    <LemonButton
                                                        fullWidth
                                                        role="menuitem"
                                                        size="small"
                                                        onClick={() => setFilters({ createdBy: 'All users' })}
                                                        type="tertiary"
                                                    >
                                                        Clear selection
                                                    </LemonButton>
                                                </li>
                                            </>
                                        )}
                                    </ul>
                                </div>
                            }
                        >
                            <LemonButton size="small" type="secondary">
                                {createdBy !== 'All users' && (createdBy as number[]).length > 0
                                    ? `Created by (${(createdBy as number[]).length})`
                                    : 'Created by'}
                            </LemonButton>
                        </LemonDropdown>
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
