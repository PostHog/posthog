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
import type { AccountCustomPropertyFilter } from '~/types'

import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import { ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST } from './accountsCustomPropertyFilters'
import { accountsLogic, RoleFilterValue } from './accountsLogic'
import { AccountsOverviewTilesButton } from './AccountsOverviewTilesButton'
import { AccountsViewSelector } from './AccountsViewSelector'

export function AccountsTabFilters(): JSX.Element {
    const {
        searchInput,
        tagsFilter,
        allRolesUnassigned,
        assignedToCurrentUser,
        assignedToFilter,
        customPropertyFilters,
    } = useValues(accountsLogic)
    const { responseLoading: accountsLoading } = useValues(dataNodeLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAllRolesUnassigned,
        setAssignedToCurrentUser,
        setAssignedToFilter,
        setCustomPropertyFilters,
        refresh,
        reportFilterChange,
    } = useActions(accountsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const { customPropertyTaxonomicOptions } = useValues(accountsColumnConfigLogic)

    const tagsButtonLabel =
        tagsFilter.length === 0 ? 'All tags' : tagsFilter.length === 1 ? tagsFilter[0] : `${tagsFilter.length} tags`

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search by name or ID..."
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
                        unassignedOnly={allRolesUnassigned}
                        onUnassignedOnlyChange={(value) => {
                            setAllRolesUnassigned(value)
                            reportFilterChange('unassigned_only')
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

                    {customPropertyTaxonomicOptions.length > 0 && (
                        <PropertyFilters
                            propertyFilters={customPropertyFilters}
                            onChange={(filters) => {
                                setCustomPropertyFilters(filters as AccountCustomPropertyFilter[])
                                reportFilterChange('custom_property')
                            }}
                            pageKey="customer-analytics-accounts-custom-properties"
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.AccountCustomProperties]}
                            taxonomicFilterOptionsFromProp={{
                                [TaxonomicFilterGroupType.AccountCustomProperties]: customPropertyTaxonomicOptions,
                            }}
                            operatorAllowlist={ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST}
                            buttonSize="small"
                            hasRowOperator={false}
                        />
                    )}
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
    unassignedOnly,
    onUnassignedOnlyChange,
}: {
    value: RoleFilterValue
    onChange: (value: RoleFilterValue) => void
    unassignedOnly: boolean
    onUnassignedOnlyChange: (value: boolean) => void
}): JSX.Element {
    const buttonLabel = unassignedOnly
        ? 'Unassigned'
        : value.length === 0
          ? 'Assigned to anyone'
          : value.length === 1
            ? 'Assigned to 1 person'
            : `Assigned to ${value.length} people`
    const hasFilter = unassignedOnly || value.length > 0
    return (
        <div className="flex gap-1 items-center" data-attr="accounts-assigned-to-filter">
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64 flex flex-col gap-2">
                        <LemonCheckbox
                            checked={unassignedOnly}
                            onChange={onUnassignedOnlyChange}
                            label="Unassigned only"
                            data-attr="accounts-unassigned-filter"
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
                    onClick={() => {
                        if (unassignedOnly) {
                            onUnassignedOnlyChange(false)
                        }
                        if (value.length > 0) {
                            onChange([])
                        }
                    }}
                    tooltip="Clear assigned-to filter"
                />
            )}
        </div>
    )
}
