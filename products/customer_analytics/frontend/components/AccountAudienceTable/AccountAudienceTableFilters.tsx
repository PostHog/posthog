import { useActions, useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { AccountAssignmentFilter } from 'lib/components/AccountAssignmentFilter/AccountAssignmentFilter'

import { tagsModel } from '~/models/tagsModel'

import { AccountsColumnConfigurator } from '../Accounts/AccountsColumnConfigurator'
import { accountAudienceTableLogic } from './accountAudienceTableLogic'

export function AccountAudienceTableFilters(): JSX.Element {
    const { searchInput, tagsFilter, assignmentStatus, assignedToFilter, assignedToCurrentUser } =
        useValues(accountAudienceTableLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAssignmentStatus,
        setAssignedToFilter,
        setAssignedToCurrentUser,
        reportFilterChange,
    } = useActions(accountAudienceTableLogic)
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)

    const tagsButtonLabel =
        tagsFilter.length === 0 ? 'All tags' : tagsFilter.length === 1 ? tagsFilter[0] : `${tagsFilter.length} tags`

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <LemonInput
                type="search"
                placeholder="Search by name or ID..."
                value={searchInput}
                onChange={setSearchInput}
                size="small"
                className="min-w-64"
                data-attr="account-audience-search"
            />
            <LemonDropdown
                closeOnClickInside={false}
                onVisibilityChange={(open) => open && loadTagsIfNeeded()}
                overlay={
                    <div className="p-2 min-w-64">
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={tagsFilter}
                            options={(tagsAvailable || []).map((tag: string) => ({ key: tag, label: tag }))}
                            loading={tagsLoading}
                            onChange={(tags) => {
                                setTagsFilter(tags)
                                reportFilterChange('tag')
                            }}
                            placeholder="Select or type tags..."
                            data-attr="account-audience-tags-filter"
                        />
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {tagsButtonLabel}
                </LemonButton>
            </LemonDropdown>
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
                    trigger: 'account-audience-assigned-filter',
                    unassigned: 'account-audience-unassigned-filter',
                    assigned: 'account-audience-assigned-status-filter',
                    all: 'account-audience-all-assignment-filter',
                }}
            />
            <LemonCheckbox
                checked={assignedToCurrentUser}
                onChange={(checked) => {
                    setAssignedToCurrentUser(checked)
                    reportFilterChange('my_accounts')
                }}
                label="My accounts"
                data-attr="account-audience-my-accounts-filter"
            />
            <div className="ml-auto">
                <AccountsColumnConfigurator />
            </div>
        </div>
    )
}
