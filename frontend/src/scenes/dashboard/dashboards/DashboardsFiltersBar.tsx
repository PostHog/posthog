import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { IconChevronDown, IconPin, IconPinFilled, IconShare } from '@posthog/icons'
import { LemonInput, Popover } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

interface DashboardsFiltersBarProps {
    extraActions?: JSX.Element | JSX.Element[]
}

export function DashboardsFiltersBar({ extraActions }: DashboardsFiltersBarProps): JSX.Element {
    const { filters, currentTab, filteredTags, tagSearch, showTagPopover } = useValues(dashboardsLogic)
    const { setFilters, setTagSearch, setShowTagPopover, setSearch } = useActions(dashboardsLogic)

    const debouncedSetSearch = useDebouncedCallback((value: string) => {
        setSearch(value)
    }, 300)

    const handleTagToggle = (tag: string): void => {
        const selected = new Set(filters.tags || [])
        if (selected.has(tag)) {
            selected.delete(tag)
        } else {
            selected.add(tag)
        }
        setFilters({ tags: Array.from(selected) })
    }

    return (
        <div className="flex justify-between gap-2 flex-wrap mb-4">
            <LemonInput
                type="search"
                placeholder="Search for dashboards"
                onChange={(value) => {
                    setFilters({ search: value })
                    debouncedSetSearch(value)
                }}
                value={filters.search}
            />
            <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span>Filter to:</span>
                    {currentTab !== DashboardsTab.Pinned && (
                        <div className="flex items-center gap-2">
                            <LemonButton
                                active={filters.pinned}
                                type="secondary"
                                size="small"
                                onClick={() => setFilters({ pinned: !filters.pinned })}
                                icon={filters.pinned ? <IconPinFilled /> : <IconPin />}
                            >
                                Pinned
                            </LemonButton>
                        </div>
                    )}
                    <Popover
                        visible={showTagPopover}
                        onClickOutside={() => setShowTagPopover(false)}
                        overlay={
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
                                                            checked={filters.tags?.includes(tag) || false}
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
                                            {tagSearch ? <span>No matching tags</span> : <span>No tags</span>}
                                        </div>
                                    ) : null}
                                    {(filters.tags?.length || 0) > 0 && (
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
                        }
                    >
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronDown />}
                            sideIcon={null}
                            active={(filters.tags?.length || 0) > 0}
                            onClick={() => setShowTagPopover(!showTagPopover)}
                        >
                            Tags
                            {(filters.tags?.length || 0) > 0 && (
                                <span className="ml-1 text-xs">({filters.tags?.length})</span>
                            )}
                        </LemonButton>
                    </Popover>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={filters.shared}
                            type="secondary"
                            size="small"
                            onClick={() => setFilters({ shared: !filters.shared })}
                            icon={<IconShare />}
                        >
                            Shared
                        </LemonButton>
                    </div>
                </div>
                {currentTab !== DashboardsTab.Yours && (
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={filters.createdBy === 'All users' ? null : filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || 'All users' })}
                        />
                    </div>
                )}
                {extraActions}
            </div>
        </div>
    )
}
