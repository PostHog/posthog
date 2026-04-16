import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { createFuse } from 'lib/utils/fuseSearch'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberScopedApiKeysResponse, OrganizationMemberType } from '~/types'

import type { membersLogicType } from './membersLogicType'

export interface MembersFuse extends Fuse<OrganizationMemberType> {}

const PAGINATION_LIMIT = 200
const SEARCH_DEBOUNCE_MS = 300

export const membersLogic = kea<membersLogicType>([
    path(['scenes', 'organization', 'membersLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        ensureAllMembersLoaded: true,
        loadAllMembers: true,
        loadAllMembersExhaustive: true,
        loadMemberUpdates: true,
        loadMemberScopedApiKeys: (member: OrganizationMemberType) => ({ member }),
        setSearch: (search: string) => ({ search }),
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
        postRemoveMember: (userUuid: string) => ({ userUuid }),
    }),
    loaders(({ values, actions }) => ({
        members: {
            __default: null as OrganizationMemberType[] | null,
            loadAllMembers: async () => {
                const response = await api.organizationMembers.list({
                    limit: PAGINATION_LIMIT,
                })
                return response.results
            },
            loadAllMembersExhaustive: async () => {
                return await api.organizationMembers.listAll({
                    limit: PAGINATION_LIMIT,
                })
            },
            loadMemberUpdates: async () => {
                const newestMemberUpdate = values.members?.sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1))?.[0]

                if (!newestMemberUpdate || !values.members) {
                    return null
                }

                const membersResponse = await api.organizationMembers.list({
                    updated_after: newestMemberUpdate.updated_at,
                })

                const members = [...values.members]

                membersResponse.results.forEach((member) => {
                    // Update or add the members
                    const existingIndex = members.findIndex((m) => m.user.uuid === member.user.uuid)
                    if (existingIndex !== -1) {
                        members[existingIndex] = member
                    } else {
                        members.push(member)
                    }
                })

                return members
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.organizationMembers.delete(member.user.uuid)
                lemonToast.success(
                    <>
                        Removed <b>{member.user.first_name}</b> from organization
                    </>
                )
                actions.postRemoveMember(member.user.uuid)
                return values.members?.filter((thisMember) => thisMember.user.id !== member.user.id) ?? null
            },
            changeMemberAccessLevel: async ({ member, level }) => {
                const updatedMember = await api.organizationMembers.update(member.user.uuid, { level })
                lemonToast.success(
                    <>
                        Made <b>{member.user.first_name}</b> organization {membershipLevelToName.get(level)}
                    </>
                )
                // reload organization to account for no longer being organization owner
                if (level === OrganizationMembershipLevel.Owner) {
                    organizationLogic.actions.loadCurrentOrganization()
                }

                if (!values.members) {
                    return null
                }
                const updatedMembers = [...values.members]

                const existingIndex = values.members.findIndex((m) => m.user.uuid === member.user.uuid)
                if (existingIndex !== -1) {
                    updatedMembers[existingIndex] = updatedMember
                }
                return updatedMembers
            },
        },
        searchResults: {
            __default: null as OrganizationMemberType[] | null,
            searchMembers: async (search: string) => {
                if (!search) {
                    return null
                }
                const response = await api.organizationMembers.list({
                    search,
                    limit: PAGINATION_LIMIT,
                })
                return response.results
            },
        },
        scopedApiKeys: {
            __default: null as OrganizationMemberScopedApiKeysResponse | null,
            loadMemberScopedApiKeys: async ({ member }: { member: OrganizationMemberType }) => {
                try {
                    const res = await api.organizationMembers.scopedApiKeys.list(member.user.uuid)
                    return res
                } catch {
                    return null
                }
            },
        },
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    selectors({
        sortedMembers: [
            (s) => [s.members],
            (members): OrganizationMemberType[] | null => {
                if (!members) {
                    return null
                }
                return members.sort((a, b) => (a.user.first_name > b.user.first_name ? 1 : -1))
            },
        ],
        meFirstMembers: [
            (s) => [s.sortedMembers, s.user],
            (members, user): OrganizationMemberType[] => {
                const me = user && members?.find((member) => member.user.uuid === user.uuid)
                const result: OrganizationMemberType[] = me ? [me] : []
                for (const member of members ?? []) {
                    if (!user || member.user.uuid !== user.uuid) {
                        result.push(member)
                    }
                }
                return result
            },
        ],
        membersFuse: [
            (s) => [s.meFirstMembers],
            (members): MembersFuse =>
                createFuse<OrganizationMemberType>(members ?? [], {
                    keys: ['user.first_name', 'user.last_name', 'user.email'],
                }),
        ],
        filteredMembers: [
            (s) => [s.meFirstMembers, s.membersFuse, s.search, s.searchResults],
            (members, membersFuse, search, searchResults): OrganizationMemberType[] => {
                if (!search) {
                    return members ?? []
                }
                // Use server-side results when available, fall back to client-side Fuse.js
                if (searchResults) {
                    return searchResults
                }
                return membersFuse.search(search).map((result) => result.item)
            },
        ],
        memberCount: [
            (s) => [s.user, s.sortedMembers],
            (user, members): number => {
                // Typically we can rely on the app context but just in case we use the loaded members if present
                const count = user?.organization?.member_count
                return Math.max(count ?? 0, members?.length ?? 0)
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },

        ensureAllMembersLoaded: async () => {
            if (values.membersLoading) {
                return
            }
            if (!values.members) {
                actions.loadAllMembers()
            } else {
                actions.loadMemberUpdates()
            }
        },

        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.searchMembers(search)
        },
    })),

    permanentlyMount(),
])
