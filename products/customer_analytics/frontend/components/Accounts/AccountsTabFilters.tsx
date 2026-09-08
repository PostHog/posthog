import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
} from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { tagsModel } from '~/models/tagsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { AnyPropertyFilter } from '~/types'

import { AccountRelationshipOperatorValueSelect } from './AccountRelationshipOperatorValueSelect'
import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import { accountsLogic, AssignmentStatus, RoleFilterValue } from './accountsLogic'
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
    const { searchInput, tagsFilter, assignmentStatus, assignedToCurrentUser, assignedToFilter, accountFilters } =
        useValues(accountsLogic)
    const { responseLoading: accountsLoading } = useValues(dataNodeLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAssignmentStatus,
        setAssignedToCurrentUser,
        setAssignedToFilter,
        updateAccountFilters,
        refresh,
        reportFilterChange,
    } = useActions(accountsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
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
                        overlay={
                            <div className="p-2 min-w-64">
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={tagsFilter}
                                    options={(tagsAvailable || []).map((t: string) => ({ key: t, label: t }))}
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

                    <AssignedToPicker
                        value={assignedToFilter}
                        onChange={(value) => {
                            setAssignedToFilter(value)
                            reportFilterChange('assigned_to')
                        }}
                        status={assignmentStatus}
                        onStatusChange={(status) => {
                            setAssignmentStatus(status)
                            reportFilterChange('assignment_status')
                        }}
                    />

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

                    <PropertyFilters
                        propertyFilters={accountFilters as unknown as AnyPropertyFilter[]}
                        onChange={(filters) => updateAccountFilters(filters as unknown as AccountFilter[])}
                        pageKey="customer-analytics-accounts-custom-properties"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.AccountFields,
                            TaxonomicFilterGroupType.AccountRelationships,
                            TaxonomicFilterGroupType.AccountCustomProperties,
                        ]}
                        taxonomicFilterOptionsFromProp={{
                            [TaxonomicFilterGroupType.AccountFields]: ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
                            [TaxonomicFilterGroupType.AccountRelationships]: relationshipTaxonomicOptions,
                            [TaxonomicFilterGroupType.AccountCustomProperties]: customPropertyTaxonomicOptions,
                        }}
                        operatorAllowlist={ACCOUNT_FILTER_OPERATOR_ALLOWLIST}
                        staticValueOptions={accountFilterStaticValueOptions}
                        renderOperatorValueSelect={(filter, onChange) =>
                            isAccountRelationshipFilter(filter) ? (
                                <AccountRelationshipOperatorValueSelect filter={filter} onChange={onChange} />
                            ) : null
                        }
                        buttonSize="small"
                        hasRowOperator={false}
                    />
                </div>
                <div className="flex flex-wrap gap-2 items-center">
                    <AccountsOverviewTilesButton />
                    <AccountsColumnConfigurator />
                </div>
            </div>
        </div>
    )
}

function AssignedToPicker({
    value,
    onChange,
    status,
    onStatusChange,
}: {
    value: RoleFilterValue
    onChange: (value: RoleFilterValue) => void
    status: AssignmentStatus
    onStatusChange: (status: AssignmentStatus) => void
}): JSX.Element {
    const buttonLabel =
        status === 'unassigned'
            ? 'Unassigned only'
            : status === 'all'
              ? 'All accounts'
              : value.length === 0
                ? 'Assigned to anyone'
                : value.length === 1
                  ? 'Assigned to 1 person'
                  : `Assigned to ${value.length} people`
    // `all` is the default, so anything else is an active choice worth a clear button.
    const hasFilter = status !== 'all'
    return (
        <div className="flex gap-1 items-center" data-attr="accounts-assigned-to-filter">
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64 flex flex-col gap-2">
                        <LemonCheckbox
                            checked={status === 'unassigned'}
                            onChange={(checked) => checked && onStatusChange('unassigned')}
                            label="Unassigned only"
                            data-attr="accounts-unassigned-filter"
                        />
                        <LemonCheckbox
                            checked={status === 'assigned'}
                            onChange={(checked) => checked && onStatusChange('assigned')}
                            label="Assigned to anyone"
                            data-attr="accounts-assigned-filter"
                        />
                        <LemonCheckbox
                            checked={status === 'all'}
                            onChange={(checked) => checked && onStatusChange('all')}
                            label="All assignment statuses"
                            data-attr="accounts-all-assignment-filter"
                        />
                        <LemonDivider className="my-0" />
                        <MemberSelectMultiple
                            idKey="id"
                            value={value}
                            onChange={(users) => onChange(users.map((user) => user.id))}
                        />
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {buttonLabel}
                </LemonButton>
            </LemonDropdown>
            {hasFilter && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => onStatusChange('all')}
                    tooltip="Clear assignment filter"
                />
            )}
        </div>
    )
}
