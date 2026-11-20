import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheckCircle, IconChip, IconClock, IconLaptop, IconLock, IconPencil, IconTrash } from '@posthog/icons'
import { Button, DataTable, Empty, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import { IconLink, IconSync } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { getAuthenticatorTypeText, getVerificationStatusText } from './passkeyDisplay'
import { PasskeyCredential, passkeySettingsLogic } from './passkeySettingsLogic'

function VerificationStatusIcon({ verified, verifying }: { verified: boolean; verifying: boolean }): JSX.Element {
    if (verifying) {
        return <IconSync className="text-warning-foreground animate-spin motion-reduce:animate-none" />
    }
    if (verified) {
        return <IconCheckCircle className="text-success-foreground" />
    }
    return <IconClock className="text-muted-foreground" />
}

function AuthenticatorTypeIcon({ type }: { type: PasskeyCredential['authenticator_type'] }): JSX.Element {
    switch (type) {
        case 'hardware':
            return <IconChip className="text-muted-foreground" />
        case 'platform':
            return <IconLaptop className="text-muted-foreground" />
        case 'hybrid':
            return <IconLink className="text-muted-foreground" />
        default:
            return <IconLock className="text-muted-foreground" />
    }
}

export function QuillPasskeyList(): JSX.Element {
    const { passkeys, passkeysLoading, verifyingPasskeyId } = useValues(passkeySettingsLogic)
    const { verifyPasskey, openDeleteModal, openRenameModal } = useActions(passkeySettingsLogic)

    const columns = useMemo<ColumnDef<PasskeyCredential>[]>(
        () => [
            {
                id: 'label',
                header: 'Name',
                accessorKey: 'label',
                cell: ({ row }) => (
                    <div className="flex items-center gap-2">
                        <IconLock className="text-muted-foreground" />
                        <Text size="xs" weight="medium" render={<span />}>
                            {row.original.label}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'authenticator_type',
                header: 'Type',
                enableSorting: false,
                cell: ({ row }) => (
                    <div className="flex items-center gap-2">
                        <AuthenticatorTypeIcon type={row.original.authenticator_type} />
                        <span>{getAuthenticatorTypeText(row.original.authenticator_type)}</span>
                    </div>
                ),
            },
            {
                id: 'verified',
                header: 'Status',
                enableSorting: false,
                cell: ({ row }) => {
                    const record = row.original
                    const verifying = verifyingPasskeyId === record.id

                    return (
                        <div className="flex items-center gap-2">
                            <VerificationStatusIcon verified={record.verified} verifying={verifying} />
                            <span>{getVerificationStatusText(record.verified, verifying)}</span>
                            {!record.verified && !verifying && (
                                <Button
                                    size="sm"
                                    onClick={() => verifyPasskey(record.id)}
                                    tooltip="Verify this passkey"
                                >
                                    Verify
                                </Button>
                            )}
                        </div>
                    )
                },
            },
            {
                id: 'created_at',
                header: 'Added',
                accessorFn: (record) => new Date(record.created_at).getTime(),
                cell: ({ row }) => humanFriendlyDetailedTime(row.original.created_at),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <div className="flex justify-end gap-1">
                        <Button
                            size="icon"
                            aria-label="Rename"
                            tooltip="Rename"
                            onClick={() => openRenameModal(row.original.id, row.original.label)}
                        >
                            <IconPencil />
                        </Button>
                        <Button
                            variant="destructive-outline"
                            size="icon"
                            aria-label="Delete"
                            tooltip="Delete"
                            onClick={() => openDeleteModal(row.original.id)}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                ),
            },
        ],
        [verifyingPasskeyId, verifyPasskey, openDeleteModal, openRenameModal]
    )

    if (passkeysLoading && passkeys.length === 0) {
        return <Skeleton className="h-24" />
    }

    return (
        <div aria-busy={passkeysLoading}>
            <DataTable
                columns={columns}
                data={passkeys}
                fullWidth
                getRowId={(record) => String(record.id)}
                empty={
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No passkeys</EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                }
            />
        </div>
    )
}
