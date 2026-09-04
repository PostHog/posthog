import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFolder, IconPin, IconPinFilled, IconShare, IconX } from '@posthog/icons'
import { LemonInput, Popover } from '@posthog/lemon-ui'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

interface DashboardsFiltersBarProps {
    extraActions?: JSX.Element | JSX.Element[]
}

export function DashboardsFiltersBar({ extraActions }: DashboardsFiltersBarProps): JSX.Element {
    const { filters, currentTab, tagPageLoading, tagResults, tagSearch, showTagPopover } = useValues(dashboardsLogic)
    const { loadMoreTagResults, setFilters, setTagSearch, setShowTagPopover, setSearch } = useActions(dashboardsLogic)
    const tagListScrollRef = useScrollObserver({ onScrollBottom: loadMoreTagResults })

    const createdByIds = filters.createdBy === 'All users' ? [] : filters.createdBy
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
            <LemonInput type="search" placeholder="Search for dashboards" onChange={setSearch} value={filters.search} />
            <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
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
                                <div
                                    ref={tagListScrollRef}
                                    className="max-h-80 overflow-y-auto"
                                    data-attr="dashboard-tags-list"
                                    tabIndex={0}
                                    aria-label="Tags"
                                >
                                    <ul className="deprecated-space-y-px">
                                        {tagResults.map((tag: string) => (
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
                                        {!tagPageLoading && tagResults.length === 0 ? (
                                            <div className="p-2 text-secondary italic truncate border-t">
                                                {tagSearch ? <span>No matching tags</span> : <span>No tags</span>}
                                            </div>
                                        ) : null}
                                        {tagPageLoading ? (
                                            <li className="p-1" aria-label="Loading tags">
                                                <LemonSkeleton.Row
                                                    className="h-8 mb-1"
                                                    repeat={tagResults.length === 0 ? 5 : 2}
                                                    fade
                                                />
                                            </li>
                                        ) : null}
                                    </ul>
                                </div>
                                {(filters.tags?.length || 0) > 0 && (
                                    <>
                                        <div className="my-1 border-t" />
                                        <LemonButton
                                            fullWidth
                                            role="menuitem"
                                            size="small"
                                            onClick={() => setFilters({ tags: [] })}
                                            type="tertiary"
                                        >
                                            Clear selection
                                        </LemonButton>
                                    </>
                                )}
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
                    {filters.folder != null && (
                        <LemonButton
                            active
                            type="secondary"
                            size="small"
                            className="max-w-full"
                            icon={<IconFolder />}
                            sideIcon={<IconX />}
                            onClick={() => setFilters({ folder: null })}
                            tooltip="Clear folder filter"
                        >
                            <span className="truncate">{filters.folder || 'Project root'}</span>
                        </LemonButton>
                    )}
                </div>
                {currentTab !== DashboardsTab.Yours && (
                    <MemberSelectMultiplePopover
                        value={createdByIds}
                        onChange={(ids) =>
                            setFilters({
                                createdBy: ids.length > 0 ? ids : 'All users',
                            })
                        }
                    />
                )}
                {extraActions}
            </div>
        </div>
    )
}
