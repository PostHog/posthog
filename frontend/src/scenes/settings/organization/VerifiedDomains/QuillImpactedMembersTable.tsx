import type { ColumnDef } from '@tanstack/react-table'
import { useValues } from 'kea'

import { DataTable, Skeleton, Text } from '@posthog/quill'

import { CountedPaginatedResponse } from 'lib/api'
import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

export function QuillImpactedMembersTable({
    impact,
    loading,
}: {
    impact: CountedPaginatedResponse<OrganizationMemberType> | null
    loading: boolean
}): JSX.Element {
    const { user } = useValues(userLogic)

    const members = impact?.results ?? []
    const count = impact?.count ?? members.length

    const columns: ColumnDef<OrganizationMemberType>[] = [
        {
            id: 'user',
            header: 'Name',
            meta: { expand: true },
            cell: ({ row }) => {
                const member = row.original
                const name = fullName(member.user)

                return (
                    <div className="ph-no-capture flex min-w-0 items-center gap-2">
                        <QuillPersonAvatar name={name} email={member.user.email} />
                        <div className="flex min-w-0 flex-col">
                            <Text size="xs" render={<span className="truncate" />}>
                                {member.user.uuid === user?.uuid ? `${name} (you)` : name}
                            </Text>
                            <Text size="xs" variant="muted" render={<span className="truncate" />}>
                                {member.user.email}
                            </Text>
                        </div>
                    </div>
                )
            },
        },
        {
            id: 'level',
            header: 'Level',
            cell: ({ row }) => membershipLevelToName.get(row.original.level) ?? `unknown (${row.original.level})`,
        },
    ]

    if (loading && members.length === 0) {
        return <Skeleton className="h-24 w-full" />
    }

    return (
        <div className="flex flex-col gap-1">
            <DataTable
                columns={columns}
                data={members}
                getRowId={(member) => member.id}
                fullWidth
                size="sm"
                pageSize={members.length > 8 ? 8 : undefined}
            />
            {count > members.length && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {`Showing ${members.length} of ${count} members.`}
                </Text>
            )}
        </div>
    )
}
