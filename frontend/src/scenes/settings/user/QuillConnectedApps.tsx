import type { ColumnDef } from '@tanstack/react-table'
import { decode } from 'he'
import { useMemo } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import {
    Avatar,
    AvatarFallback,
    AvatarImage,
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

import type { ConnectedAppApi } from '~/generated/core/api.schemas'

import { QuillConnectedAppScopes } from './QuillConnectedAppScopes'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function QuillConnectedApps({
    apps,
    loading,
    onRevoke,
}: {
    apps: ConnectedAppApi[]
    loading: boolean
    onRevoke: (app: ConnectedAppApi) => void
}): JSX.Element {
    const columns = useMemo<ColumnDef<ConnectedAppApi>[]>(
        () => [
            {
                id: 'name',
                header: 'Application',
                enableSorting: false,
                cell: ({ row }) => {
                    // Name is HTML-escaped at ingestion; decode for display (see posthog/api/oauth/client_name.py).
                    const name = decode(row.original.name)

                    return (
                        <div className="flex flex-wrap items-center gap-2">
                            <Avatar className="rounded-md">
                                {row.original.logo_uri && (
                                    <AvatarImage
                                        src={row.original.logo_uri}
                                        alt={`${name} logo`}
                                        className="object-contain p-1"
                                    />
                                )}
                                <AvatarFallback className="rounded-md">{name.charAt(0).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            <Text size="xs" weight="medium" render={<span />}>
                                {name}
                            </Text>
                            {row.original.is_first_party ? (
                                <Badge variant="info">PostHog</Badge>
                            ) : row.original.is_verified ? (
                                <Badge variant="success">Verified</Badge>
                            ) : null}
                        </div>
                    )
                },
            },
            {
                id: 'scopes',
                header: 'Scopes',
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.scopes.length > 0 ? (
                        <QuillConnectedAppScopes scopes={row.original.scopes} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            No scopes
                        </Text>
                    ),
            },
            {
                id: 'authorized_at',
                header: 'Authorized',
                enableSorting: false,
                cell: ({ row }) => humanFriendlyDetailedTime(row.original.authorized_at),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <Button variant="destructive-outline" size="sm" onClick={() => onRevoke(row.original)}>
                        Revoke
                    </Button>
                ),
            },
        ],
        [onRevoke]
    )

    if (loading && apps.length === 0) {
        return <Skeleton data-quill className="h-32" />
    }

    return (
        <div data-quill aria-busy={loading}>
            <DataTable
                columns={columns}
                data={apps}
                fullWidth
                getRowId={(app) => app.id}
                empty={
                    <Empty>
                        <EmptyHeader>
                            <EmptyMedia>
                                <HedgehogMagnifyingGlass className="w-16 h-16" />
                            </EmptyMedia>
                            <EmptyTitle>No connected applications</EmptyTitle>
                            <EmptyDescription>
                                Apps will appear here when third-party tools connect to your account.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                }
            />
        </div>
    )
}
