import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { capitalizeFirstLetter, fullName } from 'lib/utils'
import { slugify } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'

import { OrganizationMemberType } from '~/types'

import type { membersExportLogicType } from './membersExportLogicType'
import { membersLogic } from './membersLogic'

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

export const membersExportLogic = kea<membersExportLogicType>([
    path(['scenes', 'organization', 'membersExportLogic']),
    connect(() => ({
        values: [membersLogic, ['sortedMembers', 'membersLoading'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        downloadMembersList: true,
    }),
    selectors({
        downloadMembersListDisabledReason: [
            (s) => [s.membersLoading, s.sortedMembers],
            (membersLoading, sortedMembers): string | null =>
                membersLoading && !sortedMembers?.length
                    ? 'Loading members...'
                    : !sortedMembers?.length
                      ? 'No members to export'
                      : null,
        ],
    }),
    listeners(({ values }) => ({
        downloadMembersList: () => {
            const sortedMembers = values.sortedMembers
            if (!sortedMembers?.length) {
                lemonToast.warning(values.downloadMembersListDisabledReason ?? 'No members to export')
                return
            }

            const csv = buildOrganizationMembersCsv(sortedMembers)
            const slug = slugify(values.currentOrganization?.name ?? 'organization').slice(0, 64)
            const filename = `posthog_organization_members_${slug || 'organization'}_${dayjs().format('YYYY-MM-DD')}.csv`
            const blob = new Blob([csv], { type: 'text/csv' })
            downloadBlob(blob, filename)
            lemonToast.success('Export complete!')
        },
    })),

    permanentlyMount(),
])
