import { useActions, useValues } from 'kea'

import { IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInputSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { tagsModel } from '~/models/tagsModel'

import { accountsLogic, RoleFilterValue } from './accountsLogic'

export function AccountsTabFilters(): JSX.Element {
    const { tagsFilter, allRolesUnassigned, csmFilter, accountExecutiveFilter, accountOwnerFilter, accountsLoading } =
        useValues(accountsLogic)
    const {
        setTagsFilter,
        setAllRolesUnassigned,
        setCsmFilter,
        setAccountExecutiveFilter,
        setAccountOwnerFilter,
        refresh,
    } = useActions(accountsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    const tagsButtonLabel =
        tagsFilter.length === 0 ? 'All tags' : tagsFilter.length === 1 ? tagsFilter[0] : `${tagsFilter.length} tags`

    return (
        <div className="flex flex-wrap gap-3 items-center">
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64">
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={tagsFilter}
                            options={(tagsAvailable || []).map((t: string) => ({ key: t, label: t }))}
                            onChange={setTagsFilter}
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
                    onClick={() => setTagsFilter([])}
                    tooltip="Clear tag filter"
                />
            )}

            <LemonCheckbox
                checked={allRolesUnassigned}
                onChange={setAllRolesUnassigned}
                label="Unassigned"
                disabledReason={accountsLoading ? 'Loading…' : undefined}
                data-attr="accounts-unassigned-filter"
            />

            <RolePicker label="CSM" value={csmFilter} onChange={setCsmFilter} dataAttr="accounts-csm-filter" />
            <RolePicker
                label="AE"
                value={accountExecutiveFilter}
                onChange={setAccountExecutiveFilter}
                dataAttr="accounts-ae-filter"
            />
            <RolePicker
                label="Owner"
                value={accountOwnerFilter}
                onChange={setAccountOwnerFilter}
                dataAttr="accounts-owner-filter"
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
    return (
        <div data-attr={dataAttr}>
            <MemberSelect
                size="small"
                type="secondary"
                defaultLabel={`Any ${label}`}
                value={value}
                onChange={(user) => onChange(user ? user.id : null)}
            />
        </div>
    )
}
