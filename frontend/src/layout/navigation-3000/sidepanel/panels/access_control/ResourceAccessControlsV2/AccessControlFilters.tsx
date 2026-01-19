import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils'

import { OrganizationMemberType, RoleType } from '~/types'

import { MultiSelectFilterDropdown } from './MultiselectFilterDropdown'
import { AccessControlsTab } from './types'

export interface AccessControlFiltersProps {
    activeTab: AccessControlsTab
    searchText: string
    setSearchText: (value: string) => void
    selectedRoleIds: string[]
    setSelectedRoleIds: (values: string[]) => void
    selectedMemberIds: string[]
    setSelectedMemberIds: (values: string[]) => void
    selectedResourceKeys: string[]
    setSelectedResourceKeys: (values: string[]) => void
    selectedRuleLevels: string[]
    setSelectedRuleLevels: (values: string[]) => void
    roles: RoleType[]
    members: OrganizationMemberType[]
    resources: { key: string; label: string }[]
    ruleOptions: { key: string; label: string }[]
    canUseRoles: boolean
    canEditAny: boolean
    onAddClick: () => void
}

export function AccessControlFilters(props: AccessControlFiltersProps): JSX.Element {
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

                {props.activeTab === 'roles' ? (
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
                            disabledReason={!props.canUseRoles ? 'Roles require an upgrade' : undefined}
                        >
                            Role{props.selectedRoleIds.length ? ` (${props.selectedRoleIds.length})` : ''}
                        </LemonButton>
                    </LemonDropdown>
                ) : null}

                {props.activeTab === 'members' ? (
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
                        <LemonButton type="secondary" size="small">
                            Member{props.selectedMemberIds.length ? ` (${props.selectedMemberIds.length})` : ''}
                        </LemonButton>
                    </LemonDropdown>
                ) : null}

                <LemonDropdown
                    closeOnClickInside={false}
                    placement="bottom-start"
                    overlay={
                        <MultiSelectFilterDropdown
                            title="Feature"
                            placeholder="Filter by features…"
                            values={props.selectedResourceKeys}
                            setValues={props.setSelectedResourceKeys}
                            options={props.resources.map((r) => ({ key: r.key, label: r.label }))}
                        />
                    }
                >
                    <LemonButton type="secondary" size="small">
                        Feature{props.selectedResourceKeys.length ? ` (${props.selectedResourceKeys.length})` : ''}
                    </LemonButton>
                </LemonDropdown>

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
                    <LemonButton type="secondary" size="small">
                        Access{props.selectedRuleLevels.length ? ` (${props.selectedRuleLevels.length})` : ''}
                    </LemonButton>
                </LemonDropdown>
            </div>

            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlus />}
                onClick={props.onAddClick}
                disabledReason={
                    !props.canEditAny
                        ? 'You cannot edit this'
                        : props.activeTab === 'roles' && !props.canUseRoles
                          ? 'Roles require an upgrade'
                          : undefined
                }
            >
                Add
            </LemonButton>
        </div>
    )
}
