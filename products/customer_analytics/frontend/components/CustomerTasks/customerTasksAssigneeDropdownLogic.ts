import { MakeLogicType, LogicWrapper, actions, connect, kea, path, reducers, selectors } from 'kea'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import type { OrganizationMemberType, RoleType } from '~/types'

import { isRoleAssigneeFilter, type CustomerTaskAssigneeFilter } from './customerTaskFilters'

export type CustomerTaskQuickAssigneeOption = { value: 'any' | 'me' | 'unassigned'; label: string }

const CUSTOMER_TASK_QUICK_ASSIGNEE_OPTIONS: readonly CustomerTaskQuickAssigneeOption[] = [
    { value: 'any', label: 'Anyone' },
    { value: 'me', label: 'Me' },
    { value: 'unassigned', label: 'Unassigned' },
]

export interface customerTasksAssigneeDropdownLogicValues {
    search: string
    roles: RoleType[]
    rolesLoading: boolean
    me: OrganizationMemberType | null
    meFirstMembers: OrganizationMemberType[]
    membersLoading: boolean
    quickOptions: CustomerTaskQuickAssigneeOption[]
    myRoles: RoleType[]
    otherRoles: RoleType[]
    filteredMembers: OrganizationMemberType[]
    nothingMatches: boolean
    assigneeLabel: (assignee: CustomerTaskAssigneeFilter) => string
}

export interface customerTasksAssigneeDropdownLogicActions {
    setSearch: (search: string) => { search: string }
    ensureAllMembersLoaded: () => { value: true }
}

export type customerTasksAssigneeDropdownLogicType = MakeLogicType<
    customerTasksAssigneeDropdownLogicValues,
    customerTasksAssigneeDropdownLogicActions
>

function matchesSearch(text: string, search: string): boolean {
    return text.toLowerCase().includes(search.trim().toLowerCase())
}

function memberName(member: OrganizationMemberType): string {
    return fullName(member.user) || member.user.email
}

function filterRolesBySearch(roles: RoleType[], search: string): RoleType[] {
    return roles
        .filter((role) => matchesSearch(role.name, search))
        .sort((left, right) => left.name.localeCompare(right.name))
}

export const customerTasksAssigneeDropdownLogic: LogicWrapper<customerTasksAssigneeDropdownLogicType> =
    kea<customerTasksAssigneeDropdownLogicType>([
        path([
            'products',
            'customer_analytics',
            'frontend',
            'components',
            'CustomerTasks',
            'customerTasksAssigneeDropdownLogic',
        ]),
        connect(() => ({
            values: [rolesLogic, ['roles', 'rolesLoading'], membersLogic, ['me', 'meFirstMembers', 'membersLoading']],
            actions: [membersLogic, ['ensureAllMembersLoaded']],
        })),
        actions({
            setSearch: (search: string) => ({ search }),
        }),
        reducers({
            search: ['', { setSearch: (_, { search }) => search }],
        }),
        selectors({
            quickOptions: [
                (s) => [s.search],
                (search: string): CustomerTaskQuickAssigneeOption[] =>
                    CUSTOMER_TASK_QUICK_ASSIGNEE_OPTIONS.filter((option) => matchesSearch(option.label, search)),
            ],
            myRoles: [
                (s) => [s.roles, s.me, s.search],
                (roles: RoleType[], me: OrganizationMemberType | null, search: string): RoleType[] =>
                    me
                        ? filterRolesBySearch(roles ?? [], search).filter((role) =>
                              (role.members ?? []).some((member) => member.user.uuid === me.user.uuid)
                          )
                        : [],
            ],
            otherRoles: [
                (s) => [s.roles, s.myRoles, s.search],
                (roles: RoleType[], myRoles: RoleType[], search: string): RoleType[] => {
                    const myRoleIds = new Set(myRoles.map((role) => role.id))
                    return filterRolesBySearch(roles ?? [], search).filter((role) => !myRoleIds.has(role.id))
                },
            ],
            filteredMembers: [
                (s) => [s.meFirstMembers, s.search],
                (members: OrganizationMemberType[], search: string): OrganizationMemberType[] =>
                    members.filter(
                        (member) =>
                            matchesSearch(memberName(member), search) || matchesSearch(member.user.email, search)
                    ),
            ],
            nothingMatches: [
                (s) => [s.quickOptions, s.myRoles, s.otherRoles, s.filteredMembers, s.rolesLoading, s.membersLoading],
                (
                    quickOptions: CustomerTaskQuickAssigneeOption[],
                    myRoles: RoleType[],
                    otherRoles: RoleType[],
                    filteredMembers: OrganizationMemberType[],
                    rolesLoading: boolean,
                    membersLoading: boolean
                ): boolean =>
                    !rolesLoading &&
                    !membersLoading &&
                    quickOptions.length + myRoles.length + otherRoles.length + filteredMembers.length === 0,
            ],
            assigneeLabel: [
                (s) => [s.roles, s.meFirstMembers],
                (roles: RoleType[], members: OrganizationMemberType[]) =>
                    (assignee: CustomerTaskAssigneeFilter): string => {
                        if (isRoleAssigneeFilter(assignee)) {
                            return (roles ?? []).find((role) => role.id === assignee.roleId)?.name ?? 'Role'
                        }
                        if (typeof assignee === 'number') {
                            const member = members.find((candidate) => candidate.user.id === assignee)
                            return member ? memberName(member) : 'Member'
                        }
                        return (
                            CUSTOMER_TASK_QUICK_ASSIGNEE_OPTIONS.find((option) => option.value === assignee)?.label ??
                            'Anyone'
                        )
                    },
            ],
        }),
    ])
