import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { AccountAssignmentFilter } from 'lib/components/AccountAssignmentFilter/AccountAssignmentFilter'
import { TagSelect } from 'lib/components/TagSelect'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import { AccountsFilterGroups } from './AccountsFilterGroups'
import { accountsLogic } from './accountsLogic'
import { AccountsOverviewTilesButton } from './AccountsOverviewTilesButton'
import { AccountsViewSelector } from './AccountsViewSelector'

export function AccountsTabFilters(): JSX.Element {
    const { searchInput, tagsFilter, assignmentStatus, assignedToCurrentUser, assignedToFilter } =
        useValues(accountsLogic)
    const { responseLoading: accountsLoading } = useValues(dataNodeLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAssignmentStatus,
        setAssignedToCurrentUser,
        setAssignedToFilter,
        refresh,
        reportFilterChange,
    } = useActions(accountsLogic)

    const tagsButtonLabel =
        tagsFilter.length === 0 ? 'All tags' : tagsFilter.length === 1 ? tagsFilter[0] : `${tagsFilter.length} tags`

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search by name, ID, or email..."
                        value={searchInput}
                        onChange={setSearchInput}
                        size="small"
                        className="min-w-64"
                        data-attr="accounts-search"
                    />
                    <AccountsViewSelector />
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={accountsLoading}
                    disabledReason={accountsLoading ? 'Loading…' : undefined}
                    onClick={refresh}
                    size="small"
                    data-attr="accounts-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
            <div className="flex flex-wrap gap-2 items-center">
                <div className="contents">
                    <TagSelect
                        value={tagsFilter}
                        onChange={(tags) => {
                            setTagsFilter(tags)
                            reportFilterChange('tag')
                        }}
                        listDataAttr="accounts-tags-filter"
                    >
                        {() => (
                            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                                {tagsButtonLabel}
                            </LemonButton>
                        )}
                    </TagSelect>
                    {tagsFilter.length > 0 && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconX />}
                            onClick={() => {
                                setTagsFilter([])
                                reportFilterChange('tag')
                            }}
                            tooltip="Clear tag filter"
                        />
                    )}

                    <div className="flex gap-1 items-center" data-attr="accounts-assigned-to-filter">
                        <AccountAssignmentFilter
                            assignedToUserIds={assignedToFilter}
                            onAssignedToUserIdsChange={(userIds) => {
                                setAssignedToFilter(userIds)
                                reportFilterChange('assigned_to')
                            }}
                            status={assignmentStatus}
                            onStatusChange={(status) => {
                                setAssignmentStatus(status)
                                reportFilterChange('assignment_status')
                            }}
                            dataAttrs={{
                                unassigned: 'accounts-unassigned-filter',
                                assigned: 'accounts-assigned-filter',
                                all: 'accounts-all-assignment-filter',
                            }}
                        />
                        {assignmentStatus !== 'all' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconX />}
                                onClick={() => {
                                    setAssignmentStatus('all')
                                    reportFilterChange('assignment_status')
                                }}
                                tooltip="Clear assignment filter"
                            />
                        )}
                    </div>

                    <LemonCheckbox
                        checked={assignedToCurrentUser}
                        onChange={(value) => {
                            setAssignedToCurrentUser(value)
                            reportFilterChange('my_accounts')
                        }}
                        label="My accounts"
                        info="Shortcut for Assigned to: you — accounts where you are the CSM or account executive"
                        disabledReason={accountsLoading ? 'Loading…' : undefined}
                        data-attr="accounts-my-accounts-filter"
                    />

                    <AccountsFilterGroups />
                </div>
                <div className="flex flex-wrap gap-2 items-center ml-auto">
                    <AccountsOverviewTilesButton />
                    <AccountsColumnConfigurator />
                </div>
            </div>
        </div>
    )
}
