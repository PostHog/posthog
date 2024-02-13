import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

import type { membersLogicType } from './membersLogicType'

export interface MembersFuse extends Fuse<OrganizationMemberType> {}

export const membersLogic = kea<membersLogicType>([
    path(['scenes', 'organization', 'Settings', 'membersLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        setSearch: (search) => ({ search }),
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
        postRemoveMember: (userUuid: string) => ({ userUuid }),
    }),
    loaders(({ values, actions }) => ({
        members: {
            __default: [] as OrganizationMemberType[],
            loadMembers: async () => {
                return (await api.get('api/organizations/@current/members/?limit=250')).results
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.delete(`api/organizations/@current/members/${member.user.uuid}/`)
                lemonToast.success(
                    <>
                        Removed <b>{member.user.first_name}</b> from organization
                    </>
                )
                actions.postRemoveMember(member.user.uuid)
                return values.members.filter((thisMember) => thisMember.user.id !== member.user.id)
            },
        },
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    selectors({
        meFirstMembers: [
            (s) => [s.members, s.user],
            (members, user) => {
                const me = user && members.find((member) => member.user.uuid === user.uuid)
                const result: OrganizationMemberType[] = me ? [me] : []
                for (const member of members) {
                    if (!user || member.user.uuid !== user.uuid) {
                        result.push(member)
                    }
                }
                return result
            },
        ],
        membersFuse: [
            (s) => [s.members],
            (members): MembersFuse =>
                new Fuse<OrganizationMemberType>(members, {
                    keys: ['user.first_name', 'user.last_name', 'user.email'],
                    threshold: 0.3,
                }),
        ],
        filteredMembers: [
            (s) => [s.members, s.membersFuse, s.search],
            (members, membersFuse, search) =>
                search ? membersFuse.search(search).map((result) => result.item) : members,
        ],
    }),
    listeners(({ actions }) => ({
        changeMemberAccessLevel: async ({ member, level }) => {
            await api.update(`api/organizations/@current/members/${member.user.uuid}/`, { level })
            lemonToast.success(
                <>
                    Made <b>{member.user.first_name}</b> organization {membershipLevelToName.get(level)}
                </>
            )
            // reload organization to account for no longer being organization owner
            if (level === OrganizationMembershipLevel.Owner) {
                organizationLogic.actions.loadCurrentOrganization()
            }
            actions.loadMembers()
        },
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: actions.loadMembers,
    })),
])
