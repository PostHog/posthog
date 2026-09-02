import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFolder, IconPin, IconPinFilled, IconShare } from '@posthog/icons'
import { LemonInput, LemonSearchableSelect, Popover } from '@posthog/lemon-ui'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

interface DashboardsFiltersBarProps {
    extraActions?: JSX.Element | JSX.Element[]
}

export function DashboardsFiltersBar({ extraActions }: DashboardsFiltersBarProps): JSX.Element {
    const { filters, currentTab, filteredTags, tagSearch, showTagPopover, folderOptions } = useValues(dashboardsLogic)
    const { setFilters, setTagSearch, setShowTagPopover, setSearch } = useActions(dashboardsLogic)

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
                    <LemonSearchableSelect<string | null>
                        value={filters.folder ?? null}
                        onChange={(folder) => setFilters({ folder })}
                        options={[
                            { value: null, label: 'All folders' },
                            ...folderOptions.map((folder) => ({
                                value: folder,
                                // A dashboard sitting at the top of the project tree has an empty folder path.
                                label: folder || 'Project root',
                            })),
                        ]}
                        active={filters.folder != null}
                        type="secondary"
                        size="small"
                        icon={<IconFolder />}
                        disabledReason={
                            folderOptions.length === 0 ? 'No dashboards are filed in a folder yet' : undefined
                        }
                        dropdownMatchSelectWidth={false}
                        truncateText={{ maxWidthClass: 'max-w-60' }}
                        searchPlaceholder="Search folders"
                        noResultsMessage="No matching folders"
                        searchInputDataAttr="dashboards-folder-filter-search"
                        data-attr="dashboards-folder-filter"
                    />
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
