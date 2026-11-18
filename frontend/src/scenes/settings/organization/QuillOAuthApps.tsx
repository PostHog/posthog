import type { ColumnDef } from '@tanstack/react-table'
import { decode } from 'he'
import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
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

import { IconKey } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { oauthAppsLogic } from './oauthAppsLogic'

function CopyableCode({ value, label, onCopy }: { value: string; label: string; onCopy: () => void }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-1">
            <code className="max-w-50 truncate rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs">{value}</code>
            <Button size="icon-xs" aria-label={label} tooltip={label} onClick={onCopy}>
                <IconCopy />
            </Button>
        </div>
    )
}

const columns: ColumnDef<OrganizationOAuthApplicationApi>[] = [
    {
        id: 'name',
        header: 'Application',
        cell: ({ row }) => (
            <div className="flex items-center gap-2">
                <Text size="xs" weight="semibold" render={<span />}>
                    {decode(row.original.name ?? '')}
                </Text>
                {row.original.is_verified && <Badge variant="success">Verified</Badge>}
            </div>
        ),
    },
    {
        id: 'client_id',
        header: 'Client ID',
        cell: ({ row }) => (
            <CopyableCode
                value={row.original.client_id ?? ''}
                label="Copy client ID"
                onCopy={() => void copyToClipboard(row.original.client_id ?? '', 'client ID')}
            />
        ),
    },
    {
        id: 'redirect_uris',
        header: 'Redirect URIs',
        cell: ({ row }) => {
            const uris = row.original.redirect_uris_list || []

            if (uris.length === 0) {
                return (
                    <Text size="xs" variant="muted" render={<span />}>
                        None
                    </Text>
                )
            }

            return (
                <div className="flex flex-col gap-0.5">
                    {uris.map((uri, i) => (
                        <CopyableCode
                            key={i}
                            value={uri}
                            label="Copy URI"
                            onCopy={() => void copyToClipboard(uri, 'redirect URI')}
                        />
                    ))}
                </div>
            )
        },
    },
    {
        id: 'created',
        header: 'Connected',
        cell: ({ row }) => (
            <Text size="xs" variant="muted" render={<span />}>
                {humanFriendlyDetailedTime(row.original.created)}
            </Text>
        ),
    },
]

export function QuillOAuthApps(): JSX.Element {
    const { oauthApps, oauthAppsLoading } = useValues(oauthAppsLogic)

    if (oauthAppsLoading && oauthApps.length === 0) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
            </div>
        )
    }

    if (oauthApps.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconKey />
                    </EmptyMedia>
                    <EmptyTitle>No connected applications</EmptyTitle>
                    <EmptyDescription>
                        Applications will appear here when third-party tools connect to your organization.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return <DataTable columns={columns} data={oauthApps} fullWidth />
}
