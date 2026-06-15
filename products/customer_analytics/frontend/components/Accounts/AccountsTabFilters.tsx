import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { tagsModel } from '~/models/tagsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { accountsLogic, RoleFilterValue } from './accountsLogic'

export function AccountsTabFilters(): JSX.Element {
    const { searchInput, tagsFilter, allRolesUnassigned, csmFilter, accountExecutiveFilter, accountOwnerFilter } =
        useValues(accountsLogic)
    const { responseLoading: accountsLoading } = useValues(dataNodeLogic)
    const {
        setSearchInput,
        setTagsFilter,
        setAllRolesUnassigned,
        setCsmFilter,
        setAccountExecutiveFilter,
        setAccountOwnerFilter,
        refresh,
        reportFilterChange,
    } = useActions(accountsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    const tagsButtonLabel =
        tagsFilter.length === 0 ? 'All tags' : tagsFilter.length === 1 ? tagsFilter[0] : `${tagsFilter.length} tags`

    return (
        <div className="flex flex-wrap gap-3 items-center">
            <LemonInput
                type="search"
                placeholder="Search by name or ID..."
                value={searchInput}
                onChange={setSearchInput}
                size="small"
                className="min-w-64"
                data-attr="accounts-search"
            />
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

            <RolePicker
                label="CSM"
                value={csmFilter}
                onChange={(value) => {
                    setCsmFilter(value)
                    reportFilterChange('csm')
                }}
                dataAttr="accounts-csm-filter"
            />
            <RolePicker
                label="AE"
                value={accountExecutiveFilter}
                onChange={(value) => {
                    setAccountExecutiveFilter(value)
                    reportFilterChange('account_executive')
                }}
                dataAttr="accounts-ae-filter"
            />
            <RolePicker
                label="Owner"
                value={accountOwnerFilter}
                onChange={(value) => {
                    setAccountOwnerFilter(value)
                    reportFilterChange('account_owner')
                }}
                dataAttr="accounts-owner-filter"
            />
            <LemonCheckbox
                checked={allRolesUnassigned}
                onChange={(value) => {
                    setAllRolesUnassigned(value)
                    reportFilterChange('unassigned_only')
                }}
                label="Unassigned only"
                disabledReason={accountsLoading ? 'Loading…' : undefined}
                data-attr="accounts-unassigned-filter"
            />

            <div className="ml-auto">
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
        </div>
    )
}

function RolePicker({
    label,
    value,
    onChange,
    dataAttr,
}: {
    label: string
    value: RoleFilterValue
    onChange: (value: RoleFilterValue) => void
    dataAttr: string
}): JSX.Element {
    const buttonLabel =
        value.length === 0 ? `Any ${label}` : value.length === 1 ? `1 ${label}` : `${value.length} ${label}s`
    return (
        <div className="flex gap-1 items-center" data-attr={dataAttr}>
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64">
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
            {value.length > 0 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => onChange([])}
                    tooltip={`Clear ${label} filter`}
                />
            )}
        </div>
    )
}
