import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFolder, IconPin, IconPinFilled, IconShare, IconX } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

interface DashboardsFiltersBarProps {
    extraActions?: JSX.Element | JSX.Element[]
}

export function DashboardsFiltersBar({ extraActions }: DashboardsFiltersBarProps): JSX.Element {
    const { filters, currentTab } = useValues(dashboardsLogic)
    const { setFilters, setSearch } = useActions(dashboardsLogic)

    const createdByIds = filters.createdBy === 'All users' ? [] : filters.createdBy

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
                    <TagSelect value={filters.tags || []} onChange={(tags) => setFilters({ tags })}>
                        {(selectedTags) => (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconChevronDown />}
                                sideIcon={null}
                                active={selectedTags.length > 0}
                            >
                                Tags
                                {selectedTags.length > 0 && (
                                    <span className="ml-1 text-xs">({selectedTags.length})</span>
                                )}
                            </LemonButton>
                        )}
                    </TagSelect>
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
