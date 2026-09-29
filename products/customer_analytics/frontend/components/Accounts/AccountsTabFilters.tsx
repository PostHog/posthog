import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { AccountAssignmentFilter } from 'lib/components/AccountAssignmentFilter/AccountAssignmentFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { tagsModel } from '~/models/tagsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { AnyPropertyFilter } from '~/types'

import { AccountRelationshipOperatorValueSelect } from './AccountRelationshipOperatorValueSelect'
import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import { accountsLogic } from './accountsLogic'
import { AccountsOverviewTilesButton } from './AccountsOverviewTilesButton'
import {
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
    ACCOUNT_FILTER_OPERATOR_ALLOWLIST,
    accountFilterStaticValueOptions,
    isAccountRelationshipFilter,
    type AccountFilter,
} from './accountsPropertyFilters'
import { AccountsViewSelector } from './AccountsViewSelector'

export function AccountsTabFilters(): JSX.Element {
    const {
        searchInput,
        tagsFilter,
        assignmentStatus,
        assignedToCurrentUser,
        assignedToFilter,
        accountFilters,
        accountFilterGroups,
    } = useValues(accountsLogic)
    const { responseLoading: accountsLoading } = useValues(dataNodeLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAssignmentStatus,
        setAssignedToCurrentUser,
        setAssignedToFilter,
        updateAccountFilters,
        addAccountFilterGroup,
        removeAccountFilterGroup,
        updateAccountFilterGroup,
        refresh,
        reportFilterChange,
    } = useActions(accountsLogic)
    const { tags: tagsAvailable, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const { customPropertyTaxonomicOptions, relationshipTaxonomicOptions } = useValues(accountsColumnConfigLogic)

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
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonDropdown
                        closeOnClickInside={false}
                        onVisibilityChange={(open) => open && loadTagsIfNeeded()}
                        overlay={
                            <div className="p-2 min-w-64">
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={tagsFilter}
                                    options={(tagsAvailable || []).map((t: string) => ({ key: t, label: t }))}
                                    loading={tagsLoading}
                                    onChange={(tags) => {
                                        setTagsFilter(tags)
                                        reportFilterChange('tag')
                                    }}
                                    placeholder="Select or type tags..."
                                    data-attr="accounts-tags-filter"
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

                    <div className="flex flex-col gap-2 min-w-64 max-w-full">
                        {[accountFilters, ...accountFilterGroups].map((filters, groupIndex) => (
                            <div key={groupIndex} className="flex flex-wrap gap-2 items-center">
                                {groupIndex > 0 && <span className="text-muted text-xs font-semibold">Or</span>}
                                <PropertyFilters
                                    propertyFilters={filters as unknown as AnyPropertyFilter[]}
                                    onChange={(updatedFilters) =>
                                        groupIndex === 0
                                            ? updateAccountFilters(updatedFilters as unknown as AccountFilter[])
                                            : updateAccountFilterGroup(
                                                  groupIndex - 1,
                                                  updatedFilters as unknown as AccountFilter[]
                                              )
                                    }
                                    pageKey={`customer-analytics-accounts-custom-properties-${groupIndex}`}
                                    taxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.AccountFields,
                                        TaxonomicFilterGroupType.AccountRelationships,
                                        TaxonomicFilterGroupType.AccountCustomProperties,
                                    ]}
                                    taxonomicFilterOptionsFromProp={{
                                        [TaxonomicFilterGroupType.AccountFields]: ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
                                        [TaxonomicFilterGroupType.AccountRelationships]: relationshipTaxonomicOptions,
                                        [TaxonomicFilterGroupType.AccountCustomProperties]:
                                            customPropertyTaxonomicOptions,
                                    }}
                                    operatorAllowlist={ACCOUNT_FILTER_OPERATOR_ALLOWLIST}
                                    staticValueOptions={accountFilterStaticValueOptions}
                                    renderOperatorValueSelect={(filter, onChange) =>
                                        isAccountRelationshipFilter(filter) ? (
                                            <AccountRelationshipOperatorValueSelect
                                                filter={filter}
                                                onChange={onChange}
                                            />
                                        ) : null
                                    }
                                    buttonSize="small"
                                    hasRowOperator
                                />
                                {groupIndex > 0 && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconX />}
                                        tooltip="Remove OR group"
                                        onClick={() => removeAccountFilterGroup(groupIndex - 1)}
                                        data-attr="accounts-remove-or-group"
                                    />
                                )}
                            </div>
                        ))}
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={addAccountFilterGroup}
                            disabledReason={
                                accountFilters.length === 0 || accountFilterGroups.some((group) => group.length === 0)
                                    ? 'Add a filter to this group first'
                                    : accountFilterGroups.length >= 9
                                      ? 'You can add up to 10 groups'
                                      : undefined
                            }
                            data-attr="accounts-add-or-group"
                        >
                            Add OR group
                        </LemonButton>
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                    <AccountsOverviewTilesButton />
                    <AccountsColumnConfigurator />
                </div>
            </div>
        </div>
    )
}
