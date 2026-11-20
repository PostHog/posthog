import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { PersonalAPIKeyType } from '~/types'

import { openDeleteKeyDialog } from '../shared/apiKeyTableUtils'
import { QuillAPIKeyActionsMenu } from '../shared/QuillAPIKeyActionsMenu'
import { isExpired, personalAPIKeysLogic } from './personalAPIKeysLogic'
import {
    DELETE_KEY_DESCRIPTION,
    EXPIRY_DATE_FORMAT,
    EXPIRY_TIME_FORMAT,
    LEGACY_HASHING_TOOLTIP,
    PersonalAPIKeyStatus,
    openRollKeyDialog,
    personalAPIKeyAccessTags,
    personalAPIKeyStatus,
} from './personalAPIKeysUtils'
import { QuillKeyTagList } from './QuillKeyTagList'
import { QuillTagList } from './QuillTagList'
import { ScopeGroupSummary } from './scopes/ScopeGroupSummary'

const STATUS_BADGE_VARIANT: Record<PersonalAPIKeyStatus['severity'], 'destructive' | 'warning'> = {
    danger: 'destructive',
    warning: 'warning',
}

function TooltipBadge({
    variant,
    tooltip,
    children,
}: {
    variant: 'destructive' | 'warning'
    tooltip: ReactNode
    children: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant={variant} />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function OptionalTime({ time }: { time: string | null }): JSX.Element {
    return time ? (
        <TZLabel time={time} />
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            Never
        </Text>
    )
}

export function QuillPersonalAPIKeysTable(): JSX.Element {
    const {
        keys,
        keysLoading,
        allOrganizations,
        allTeams,
        isPersonalApiKeyIdDisabled,
        getRestrictedOrganizationsForKey,
        getRestrictedTeamsForKey,
    } = useValues(personalAPIKeysLogic)
    const { deleteKey, loadKeys, setEditingKeyId, rollKey } = useActions(personalAPIKeysLogic)

    useEffect(() => loadKeys(), [loadKeys])

    const columns = useMemo<ColumnDef<PersonalAPIKeyType>[]>(
        () => [
            {
                id: 'label',
                header: 'Label',
                accessorKey: 'label',
                cell: ({ row }) => (
                    <div className="flex min-w-0 flex-col items-start">
                        <Button
                            variant="link-foreground"
                            size="sm"
                            className="max-w-60 truncate font-semibold"
                            onClick={() => setEditingKeyId(row.original.id)}
                        >
                            {row.original.label}
                        </Button>
                        {row.original.description && (
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <Text
                                            size="xs"
                                            variant="muted"
                                            render={<span />}
                                            className="max-w-60 truncate"
                                        />
                                    }
                                >
                                    {row.original.description}
                                </TooltipTrigger>
                                <TooltipContent className="max-w-80">{row.original.description}</TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                ),
            },
            {
                id: 'status',
                header: 'Status',
                enableSorting: false,
                cell: ({ row }) => {
                    const key = row.original
                    const status = personalAPIKeyStatus(
                        key,
                        isPersonalApiKeyIdDisabled(key.id),
                        getRestrictedOrganizationsForKey(key.id),
                        getRestrictedTeamsForKey(key.id)
                    )

                    if (!status && !key.is_legacy_hashing) {
                        return <Badge variant="success">Active</Badge>
                    }

                    return (
                        <span className="flex flex-wrap gap-1">
                            {status && (
                                <TooltipBadge variant={STATUS_BADGE_VARIANT[status.severity]} tooltip={status.tooltip}>
                                    {status.label}
                                </TooltipBadge>
                            )}
                            {key.is_legacy_hashing && (
                                <TooltipBadge variant="warning" tooltip={LEGACY_HASHING_TOOLTIP}>
                                    Legacy
                                </TooltipBadge>
                            )}
                        </span>
                    )
                },
            },
            {
                id: 'mask_value',
                header: 'Secret key',
                enableSorting: false,
                cell: ({ row }) => {
                    const key = row.original

                    if (key.local_dev_value) {
                        return (
                            <CopyToClipboardInline
                                description="personal API key"
                                tooltipMessage="Local development key. Its full value is shown because this instance has DEBUG and ALLOW_DEV_API_KEY_REVEAL set."
                                selectable
                                isValueSensitive
                                iconSize="xsmall"
                                className="font-mono text-xs max-w-60 whitespace-normal"
                            >
                                {key.local_dev_value}
                            </CopyToClipboardInline>
                        )
                    }

                    if (key.mask_value) {
                        return <span className="font-mono ph-no-capture">{key.mask_value}</span>
                    }

                    return (
                        <Tooltip>
                            <TooltipTrigger render={<span className="inline-flex cursor-default items-center gap-1" />}>
                                <span>No preview</span>
                                <IconInfo className="text-base" />
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                This key was created before the introduction of previews
                            </TooltipContent>
                        </Tooltip>
                    )
                },
            },
            {
                id: 'scopes',
                header: 'Scopes',
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.scopes[0] === '*' ? (
                        <Badge variant="warning">All access</Badge>
                    ) : (
                        <QuillTagList
                            tags={row.original.scopes}
                            tooltip={<ScopeGroupSummary scopes={row.original.scopes} />}
                            onMoreClick={() => setEditingKeyId(row.original.id)}
                        />
                    ),
            },
            {
                id: 'access',
                header: 'Org & project access',
                enableSorting: false,
                cell: ({ row }) => {
                    const key = row.original
                    const accessTags = personalAPIKeyAccessTags(
                        key,
                        allOrganizations,
                        allTeams,
                        getRestrictedOrganizationsForKey(key.id),
                        getRestrictedTeamsForKey(key.id)
                    )

                    return accessTags ? (
                        <QuillKeyTagList tags={accessTags} onMoreClick={() => setEditingKeyId(key.id)} />
                    ) : (
                        <Badge variant="warning">All access</Badge>
                    )
                },
            },
            {
                id: 'expires_at',
                header: 'Expires',
                accessorFn: (key) => (key.expires_at ? dayjs(key.expires_at).valueOf() : Number.MAX_SAFE_INTEGER),
                cell: ({ row }) =>
                    row.original.expires_at ? (
                        <TZLabel
                            time={row.original.expires_at}
                            formatDate={EXPIRY_DATE_FORMAT}
                            formatTime={EXPIRY_TIME_FORMAT}
                        />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            Never
                        </Text>
                    ),
            },
            {
                id: 'last_used_at',
                header: 'Last used',
                accessorFn: (key) => (key.last_used_at ? new Date(key.last_used_at).getTime() : 0),
                cell: ({ row }) => <OptionalTime time={row.original.last_used_at} />,
            },
            {
                id: 'created_at',
                header: 'Created',
                enableSorting: false,
                cell: ({ row }) => <TZLabel time={row.original.created_at} />,
            },
            {
                id: 'last_rolled_at',
                header: 'Last rolled',
                enableSorting: false,
                cell: ({ row }) => <OptionalTime time={row.original.last_rolled_at} />,
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const key = row.original

                    return (
                        <QuillAPIKeyActionsMenu
                            keyLabel={key.label}
                            onEdit={() => setEditingKeyId(key.id)}
                            onRoll={() => openRollKeyDialog(key, rollKey)}
                            onDelete={() => openDeleteKeyDialog(key, deleteKey, DELETE_KEY_DESCRIPTION)}
                        />
                    )
                },
            },
        ],
        [
            allOrganizations,
            allTeams,
            isPersonalApiKeyIdDisabled,
            getRestrictedOrganizationsForKey,
            getRestrictedTeamsForKey,
            setEditingKeyId,
            rollKey,
            deleteKey,
        ]
    )

    return (
        <div className="flex flex-col gap-2">
            {keys.some((key) => key.is_legacy_hashing) && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Some of your personal API keys use legacy hashing. Consider rolling or deleting them to
                            upgrade.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {keysLoading && keys.length === 0 ? (
                <Skeleton className="h-40" />
            ) : (
                <div aria-busy={keysLoading}>
                    <DataTable
                        columns={columns}
                        data={keys}
                        fullWidth
                        getRowId={(key) => key.id}
                        rowClassName={(key) =>
                            isPersonalApiKeyIdDisabled(key.id) || isExpired(key.expires_at) ? 'opacity-50' : undefined
                        }
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No personal API keys</EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}
        </div>
    )
}
