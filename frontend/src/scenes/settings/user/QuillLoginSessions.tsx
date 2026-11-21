import type { ColumnDef } from '@tanstack/react-table'
import { useValues } from 'kea'
import { useMemo } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconLeave } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { UserAuthSessionApi } from '~/generated/core/api.schemas'

import { loginSessionsLogic } from './loginSessionsLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

function MutedValue({ children }: { children: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />}>
            {children}
        </Text>
    )
}

export function QuillLoginSessions({
    hasOtherSessions,
    onRevoke,
    onRevokeOthers,
}: {
    hasOtherSessions: boolean
    onRevoke: (session: UserAuthSessionApi) => void
    onRevokeOthers: () => void
}): JSX.Element {
    const { loginSessions, loginSessionsLoading } = useValues(loginSessionsLogic)

    const columns = useMemo<ColumnDef<UserAuthSessionApi>[]>(
        () => [
            {
                id: 'device',
                header: 'Device',
                accessorKey: 'device',
                cell: ({ row }) => (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" weight="medium" render={<span />}>
                            {row.original.device || 'Unknown device'}
                        </Text>
                        {row.original.is_current && <Badge variant="success">This device</Badge>}
                    </div>
                ),
            },
            {
                id: 'location',
                header: 'Location',
                accessorKey: 'location',
                cell: ({ row }) => row.original.location || <MutedValue>Unknown</MutedValue>,
            },
            {
                id: 'login_method',
                header: 'Signed in with',
                accessorKey: 'login_method',
                cell: ({ row }) => row.original.login_method || <MutedValue>-</MutedValue>,
            },
            {
                id: 'created_at',
                header: 'Started at',
                accessorFn: (session) => (session.created_at ? new Date(session.created_at).getTime() : 0),
                cell: ({ row }) =>
                    row.original.created_at ? (
                        humanFriendlyDetailedTime(row.original.created_at, 'MMMM DD, YYYY', 'h:mm A')
                    ) : (
                        <MutedValue>Unknown</MutedValue>
                    ),
            },
            {
                id: 'last_activity',
                header: 'Last active',
                accessorFn: (session) => new Date(session.last_activity).getTime(),
                // Minute precision: last_activity is throttled to ~5-min updates, so seconds would be false precision.
                cell: ({ row }) => humanFriendlyDetailedTime(row.original.last_activity, 'MMMM DD, YYYY', 'h:mm A'),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) =>
                    row.original.is_current ? null : (
                        <Button
                            variant="destructive-outline"
                            size="icon"
                            aria-label="Log out of this device"
                            tooltip="Log out of this device"
                            disabledReason={loginSessionsLoading ? 'Working…' : undefined}
                            onClick={() => onRevoke(row.original)}
                        >
                            <IconLeave />
                        </Button>
                    ),
            },
        ],
        [loginSessionsLoading, onRevoke]
    )

    return (
        <div className="flex flex-col gap-4">
            <div>
                <Button
                    variant="destructive-outline"
                    loading={loginSessionsLoading}
                    disabledReason={hasOtherSessions ? undefined : 'No other devices to log out'}
                    onClick={onRevokeOthers}
                    data-attr="login-sessions-revoke-others"
                >
                    <IconLeave />
                    Log out everywhere else
                </Button>
            </div>
            {loginSessionsLoading && loginSessions.length === 0 ? (
                <Skeleton className="h-40" />
            ) : (
                <div aria-busy={loginSessionsLoading}>
                    <DataTable
                        columns={columns}
                        data={loginSessions}
                        fullWidth
                        getRowId={(session) => session.id}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyMedia>
                                        <HedgehogMagnifyingGlass className="w-16 h-16" />
                                    </EmptyMedia>
                                    <EmptyTitle>No active logins found</EmptyTitle>
                                    <EmptyDescription>
                                        Devices signed in to your account will appear here.
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}
        </div>
    )
}
