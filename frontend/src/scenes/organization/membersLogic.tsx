import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { capitalizeFirstLetter, fullName } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { ExporterFormat, OrganizationMemberScopedApiKeysResponse, OrganizationMemberType } from '~/types'

import type { membersLogicType } from './membersLogicType'

export interface MembersFuse extends Fuse<OrganizationMemberType> {}

const PAGINATION_LIMIT = 200

function escapeCsvField(value: string): string {
    if (/[",\n\r]/.test(value)) {
        return `"${value.replace(/"/g, '""')}"`
    }
    return value
}

function yesNo(condition: boolean): string {
    return condition ? 'Yes' : 'No'
}

function buildOrganizationMembersCsv(members: OrganizationMemberType[]): string {
    const headers = [
        'Name',
        'Email',
        'Organization role',
        '2FA enabled',
        'Email verified',
        'Social login',
        'Joined at',
        'Last login',
        'User UUID',
    ]

    const lines = [
        headers.map(escapeCsvField).join(','),
        ...members.map((member) => {
            const roleLabel = capitalizeFirstLetter(
                membershipLevelToName.get(member.level) ?? `unknown (${member.level})`
            )
            const emailVerified = member.has_social_auth || !!member.user.is_email_verified
            const row = [
                fullName(member.user),
                member.user.email,
                roleLabel,
                yesNo(member.is_2fa_enabled),
                yesNo(emailVerified),
                yesNo(member.has_social_auth),
                member.joined_at,
                member.last_login ?? '',
                member.user.uuid,
            ]
            return row.map((cell) => escapeCsvField(String(cell))).join(',')
        }),
    ]

    return lines.join('\r\n')
}

export const membersLogic = kea<membersLogicType>([
    path(['scenes', 'organization', 'membersLogic']),
    connect(() => ({
        values: [userLogic, ['user'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        downloadMembersList: true,
        ensureAllMembersLoaded: true,
        loadAllMembers: true,
        loadMemberUpdates: true,
        loadMemberScopedApiKeys: (member: OrganizationMemberType) => ({ member }),
        setSearch: (search) => ({ search }),
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
                new Fuse<OrganizationMemberType>(members ?? [], {
                    keys: ['user.first_name', 'user.last_name', 'user.email'],
                    threshold: 0.3,
                }),
        ],
        filteredMembers: [
            (s) => [s.meFirstMembers, s.membersFuse, s.search],
            (members, membersFuse, search): OrganizationMemberType[] =>
                search ? membersFuse.search(search).map((result) => result.item) : (members ?? []),
        ],
        memberCount: [
            (s) => [s.user, s.sortedMembers],
            (user, members): number => {
                // Typically we can rely on the app context but just in case we use the loaded members if present
                const count = user?.organization?.member_count
                return Math.max(count ?? 0, members?.length ?? 0)
            },
        ],
        downloadMembersListDisabledReason: [
            (s) => [s.membersLoading, s.sortedMembers],
            (membersLoading, sortedMembers): string | null =>
                membersLoading && !sortedMembers?.length
                    ? 'Loading members…'
                    : !sortedMembers?.length
                      ? 'No members to export'
                      : null,
        ],
    }),

    listeners(({ values, actions }) => ({
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },

        downloadMembersList: async () => {
            const sortedMembers = values.sortedMembers
            if (!sortedMembers?.length) {
                lemonToast.warning(values.downloadMembersListDisabledReason ?? 'No members to export')
                return
            }
            // Dynamic import avoids a static cycle: membersLogic → exportsLogic → … → hedgehogModeLogic → membersLogic
            const { exportsLogic } = await import('lib/components/ExportButton/exportsLogic')
            const csv = buildOrganizationMembersCsv(sortedMembers)
            const slug = (values.currentOrganization?.name ?? 'organization')
                .replace(/[^a-z0-9]+/gi, '_')
                .replace(/^_|_$/g, '')
                .toLowerCase()
                .slice(0, 64)
            const filename = `posthog_organization_members_${slug || 'organization'}_${dayjs().format('YYYY-MM-DD')}.csv`
            exportsLogic.actions.startExport({
                export_format: ExporterFormat.CSV,
                export_context: {
                    localData: csv,
                    filename,
                    mediaType: ExporterFormat.CSV,
                },
            })
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
    })),

    permanentlyMount(),
])
