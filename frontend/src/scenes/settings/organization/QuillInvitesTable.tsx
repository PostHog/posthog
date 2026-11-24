import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconCopy, IconX } from '@posthog/icons'
import { Badge, Button, DataTable, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { inviteLogic } from 'lib/logic/inviteLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { fullName } from 'lib/utils/strings'

import { OrganizationInviteType } from '~/types'

import { cancelInvite } from './cancelInvite'

function QuillInviteLink({ invite }: { invite: OrganizationInviteType }): JSX.Element {
    const url = new URL(`/signup/${invite.id}`, document.baseURI).href

    if (invite.is_expired) {
        return (
            <Text size="xs" weight="semibold" render={<span />} className="m-0">
                Expired – please recreate
            </Text>
        )
    }

    return (
        <Button
            variant="link-foreground"
            size="sm"
            className="max-w-full"
            onClick={() => void copyToClipboard(url, 'invite link')}
            data-attr="invite-link"
        >
            <IconCopy />
            <span className="truncate">{url}</span>
        </Button>
    )
}

export function QuillInvitesTable(): JSX.Element {
    const { invites, invitesLoading } = useValues(inviteLogic)
    const { deleteInvite } = useActions(inviteLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const columns: ColumnDef<OrganizationInviteType>[] = [
        {
            id: 'user_profile_picture',
            header: '',
            enableSorting: false,
            cell: ({ row }) => <QuillPersonAvatar name={row.original.first_name} email={row.original.target_email} />,
        },
        {
            id: 'target_email',
            header: 'Invitee',
            enableSorting: false,
            cell: ({ row }) => {
                const invite = row.original

                if (!invite.target_email) {
                    return (
                        <Text size="xs" render={<i />} className="m-0">
                            no one
                        </Text>
                    )
                }

                return (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" render={<span />} className="m-0 ph-no-capture">
                            {`${invite.target_email}${invite.first_name ? ` (${invite.first_name})` : ''}`}
                        </Text>
                        {invite.email_suppressed && (
                            <Tooltip>
                                <TooltipTrigger
                                    render={<Badge variant="destructive" data-attr="invite-email-suppressed" />}
                                >
                                    Email not delivered
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">
                                    Our email provider is blocking email to this address, usually because an earlier
                                    email bounced. Share the invite link with them directly, or contact support to
                                    unblock the address.
                                </TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            id: 'level',
            header: 'Level',
            enableSorting: false,
            cell: ({ row }) => (
                <Badge data-attr="invite-membership-level">{OrganizationMembershipLevel[row.original.level]}</Badge>
            ),
        },
        {
            id: 'created_by',
            header: 'Created by',
            accessorFn: (invite) => invite.created_by?.first_name || invite.created_by?.email || '',
            cell: ({ row }) => {
                const createdBy = row.original.created_by

                if (!createdBy) {
                    return (
                        <Text size="xs" variant="muted" render={<span />} className="m-0">
                            —
                        </Text>
                    )
                }

                return (
                    <div className="flex items-center gap-2">
                        <QuillPersonAvatar name={fullName(createdBy)} email={createdBy.email} />
                        <Text size="xs" render={<span />} className="m-0 truncate ph-no-capture">
                            {fullName(createdBy) || createdBy.email}
                        </Text>
                    </div>
                )
            },
        },
        {
            id: 'created_at',
            header: 'Created',
            accessorFn: (invite) => invite.created_at,
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 whitespace-nowrap">
                    <TZLabel time={row.original.created_at} />
                </Text>
            ),
        },
        {
            id: 'link',
            header: 'Invite Link',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => <QuillInviteLink invite={row.original} />,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) =>
                restrictionReason ? null : (
                    <Button
                        size="icon"
                        variant="destructive-outline"
                        aria-label="Cancel the invite"
                        tooltip="Cancel the invite"
                        data-attr="invite-delete"
                        onClick={() => cancelInvite(row.original, deleteInvite)}
                    >
                        <IconX />
                    </Button>
                ),
        },
    ]

    if (invitesLoading && !invites.length) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
            </div>
        )
    }

    return (
        <div data-attr="invites-table">
            <DataTable
                columns={columns}
                data={invites}
                fullWidth
                getRowId={(invite) => invite.id}
                empty={
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        There are no outstanding invitations. You can invite another team member above.
                    </Text>
                }
            />
        </div>
    )
}
