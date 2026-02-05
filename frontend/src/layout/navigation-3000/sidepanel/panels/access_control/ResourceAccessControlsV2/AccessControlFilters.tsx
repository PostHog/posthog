import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils'

import { APIScopeObject, OrganizationMemberType, RoleType } from '~/types'

import { MultiSelectFilterDropdown } from './MultiselectFilterDropdown'
import { AccessControlFilters as AccessControlFiltersType, AccessControlsTab } from './types'

export interface AccessControlFiltersProps {
    activeTab: AccessControlsTab
    searchText: string
    setSearchText: (value: string) => void
    filters: AccessControlFiltersType
    setFilters: (filters: Partial<AccessControlFiltersType>) => void
    roles: RoleType[]
    members: OrganizationMemberType[]
    resources: { key: APIScopeObject; label: string }[]
    ruleOptions: { key: string; label: string }[]
    canUseRoles: boolean
}

export function AccessControlFilters(props: AccessControlFiltersProps): JSX.Element | null {
    return (
        <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    className="w-64"
                    value={props.searchText}
                    onChange={props.setSearchText}
                    placeholder="Search"
                    size="small"
                />

                {props.activeTab === 'roles' && (
                    <RolesFilter
                        selectedRoleIds={props.filters.roleIds}
                        setSelectedRoleIds={(values) => props.setFilters({ roleIds: values })}
                        roles={props.roles}
                        canUseRoles={props.canUseRoles}
                    />
                )}

                {props.activeTab === 'members' && (
                    <MembersFilter
                        selectedMemberIds={props.filters.memberIds}
                        setSelectedMemberIds={(values) => props.setFilters({ memberIds: values })}
                        members={props.members}
                    />
                )}

                <FeaturesFilter
                    selectedResourceKeys={props.filters.resourceKeys}
                    setSelectedResourceKeys={(values) => props.setFilters({ resourceKeys: values })}
                    resources={props.resources.filter((resource) => resource.key !== 'project')}
                />

                <AccessLevelFilter
                    selectedRuleLevels={props.filters.ruleLevels}
                    setSelectedRuleLevels={(values) => props.setFilters({ ruleLevels: values })}
                    ruleOptions={props.ruleOptions}
                />
            </div>
        </div>
    )
}

function RolesFilter(props: {
    selectedRoleIds: string[]
    setSelectedRoleIds: (values: string[]) => void
    roles: RoleType[]
    canUseRoles: boolean
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <MultiSelectFilterDropdown
                    title="Role"
                    placeholder="Filter by roles…"
                    values={props.selectedRoleIds}
                    setValues={props.setSelectedRoleIds}
                    options={props.roles.map((role) => ({
                        key: role.id,
                        label: role.name,
                    }))}
                />
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                disabledReason={!props.canUseRoles ? 'You must upgrade your plan to use roles' : undefined}
            >
                Role{props.selectedRoleIds.length ? ` (${props.selectedRoleIds.length})` : ''}
            </LemonButton>
        </LemonDropdown>
    )
}

function MembersFilter(props: {
    selectedMemberIds: string[]
    setSelectedMemberIds: (values: string[]) => void
    members: OrganizationMemberType[]
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <MultiSelectFilterDropdown
                    title="Member"
                    placeholder="Filter by members…"
                    values={props.selectedMemberIds}
                    setValues={props.setSelectedMemberIds}
                    options={props.members.map((member) => ({
                        key: member.id,
                        label: fullName(member.user),
                    }))}
                />
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                Member{props.selectedMemberIds.length ? ` (${props.selectedMemberIds.length})` : ''}
            </LemonButton>
        </LemonDropdown>
    )
}

function FeaturesFilter(props: {
    selectedResourceKeys: APIScopeObject[]
    setSelectedResourceKeys: (values: APIScopeObject[]) => void
    resources: { key: APIScopeObject; label: string }[]
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <MultiSelectFilterDropdown
                    title="Feature"
                    placeholder="Filter by features…"
                    values={props.selectedResourceKeys}
                    setValues={(values) => props.setSelectedResourceKeys(values as APIScopeObject[])}
                    options={props.resources.map((r) => ({ key: r.key, label: r.label }))}
                />
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                Feature{props.selectedResourceKeys.length ? ` (${props.selectedResourceKeys.length})` : ''}
            </LemonButton>
        </LemonDropdown>
    )
}

function AccessLevelFilter(props: {
    selectedRuleLevels: string[]
    setSelectedRuleLevels: (values: string[]) => void
    ruleOptions: { key: string; label: string }[]
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <MultiSelectFilterDropdown
                    title="Access"
                    placeholder="Filter by access…"
                    values={props.selectedRuleLevels}
                    setValues={props.setSelectedRuleLevels}
                    options={props.ruleOptions}
                />
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                Access{props.selectedRuleLevels.length ? ` (${props.selectedRuleLevels.length})` : ''}
            </LemonButton>
        </LemonDropdown>
    )
}
