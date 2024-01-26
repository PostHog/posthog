import Fuse from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { ListOrganizationMembersParams, OrganizationMemberType, UserBasicType } from '~/types'

import type { membersV2LogicType, searchableMembersLogicType } from './membersV2LogicType'

export type SearchableMembersLogicProps = {
    logicKey: string
}

export interface MembersFuse extends Fuse<UserBasicType> {}

// TODO:
// 1. Offload members search to server
// 3. Modify teamMembersLogic

// 1. Add count so we can have a cheap way of checking number of users in an org (could add this to org serializer)
// 2. Load "meFirstMenber"

export const membersV2Logic = kea<membersV2LogicType>([
    path(['scenes', 'organization', 'membersCacheLogic']),

    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        postRemoveMember: (userUuid: string) => ({ userUuid }),
        loadMembers: (params: ListOrganizationMembersParams) => params,
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
    }),

    // reducers({
    //     cachedMembers: [
    //         null as OrganizationMemberType[] | null,
    //         {
    //             loadMembersSuccess: (state, { }) => {
    //                 if (state) {

    //                 }

    //                 return
    //             }
    //         }
    //     ]
    // }),

    loaders(({ values, actions }) => ({
        membersCache: {
            __default: null as OrganizationMemberType[] | null,
            loadMembers: async (params) => {
                // TODO: Support pagination
                return (await api.members.list(params)).results
            },
            clearMembers: async () => {
                return null
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.members.delete(member.user.uuid)
                lemonToast.success(
                    <>
                        Removed <b>{member.user.first_name}</b> from organization
                    </>
                )
                actions.postRemoveMember(member.user.uuid)
                return values.membersCache?.filter((thisMember) => thisMember.user.id !== member.user.id) ?? null
            },
            changeMemberAccessLevel: async ({ member, level }) => {
                const updatedMember = await api.members.update(member.user.uuid, { level })
                lemonToast.success(
                    <>
                        Made <b>{member.user.first_name}</b> organization {membershipLevelToName.get(level)}
                    </>
                )
                // reload organization to account for no longer being organization owner
                if (level === OrganizationMembershipLevel.Owner) {
                    organizationLogic.actions.loadCurrentOrganization()
                }

                if (!values.membersCache) {
                    return null
                }

                const existing = values.membersCache.find((x) => x.user.uuid === updatedMember.user.uuid)
                if (existing) {
                    existing.level = updatedMember.level
                }

                return [...values.membersCache]
            },
        },
    })),

    selectors({
        membersAsUsers: [
            (s) => [s.membersCache],
            (membersCache): UserBasicType[] | null => membersCache?.map((x) => x.user) ?? null,
        ],

        memberCount: [
            (s) => [s.user, s.membersCache],
            (user, membersCache): number => {
                return membersCache?.length ?? user.organization.member_count
            },
        ],
    }),

    listeners(() => ({
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },
    })),
])

export const searchableMembersLogic = kea<searchableMembersLogicType>([
    path(['scenes', 'organization', 'searchableMembersLogic']),
    props({} as SearchableMembersLogicProps),
    key((props) => props.logicKey),
    connect({
        values: [userLogic, ['user'], membersV2Logic, ['membersAsUsers', 'membersCacheLoading']],
        actions: [membersV2Logic, ['loadMembers']],
    }),
    actions({
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
    }),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        page: [1, { setPage: (_, { page }) => page }],
    }),
    selectors({
        meFirstMembers: [
            (s) => [s.membersAsUsers, s.user],
            (membersAsUsers, user): UserBasicType[] => {
                const users = [user]
                for (const member of membersAsUsers ?? []) {
                    if (!user || member.uuid !== user.uuid) {
                        users.push(member)
                    }
                }
                return users
            },
        ],

        membersFuse: [
            (s) => [s.meFirstMembers],
            (meFirstMembers): MembersFuse =>
                new Fuse<UserBasicType>(meFirstMembers ?? [], {
                    keys: ['first_name', 'last_name', 'email'],
                    threshold: 0.3,
                }),
        ],
        filteredMembers: [
            (s) => [s.meFirstMembers, s.membersFuse, s.search],
            (meFirstMembers, membersFuse, search): UserBasicType[] =>
                search ? membersFuse.search(search).map((result) => result.item) : meFirstMembers,
        ],

        membersLoading: [(s) => [s.membersCacheLoading], (membersCacheLoading): boolean => membersCacheLoading],
    }),

    listeners(({ actions }) => ({
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(250)
            actions.loadMembers({ search, offset: 0 })
        },
    })),
])
