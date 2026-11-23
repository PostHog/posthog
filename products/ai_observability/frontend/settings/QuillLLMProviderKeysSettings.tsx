import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    type DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
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

import { IconKey } from 'lib/lemon-ui/icons'

import { LLMProviderIcon } from '../LLMProviderIcon'
import { LLMProviderKey, LLMProviderKeyState, LLM_PROVIDER_LABELS } from './llmProviderKeysLogic'
import { formatProviderKeyDate, providerKeyStateLabel } from './providerKeyStateUtils'
import { TurnedOffEvaluationsBanner } from './TurnedOffEvaluationsBanner'

const STATE_BADGE_VARIANT: Record<LLMProviderKeyState, 'success' | 'destructive' | 'warning' | 'default'> = {
    ok: 'success',
    invalid: 'destructive',
    error: 'warning',
    unknown: 'default',
}

function QuillStateBadge({
    state,
    errorMessage,
}: {
    state: LLMProviderKeyState
    errorMessage: string | null
}): JSX.Element {
    const variant = STATE_BADGE_VARIANT[state]
    const label = providerKeyStateLabel(state)

    if (errorMessage && (state === 'invalid' || state === 'error')) {
        return (
            <Tooltip>
                <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>{label}</TooltipTrigger>
                <TooltipContent className="max-w-80">{errorMessage}</TooltipContent>
            </Tooltip>
        )
    }

    return <Badge variant={variant}>{label}</Badge>
}

export interface QuillLLMProviderKeysSettingsProps {
    isLoading: boolean
    providerKeys: LLMProviderKey[]
    validatingKeyId: string | null
    restrictionReason: string | null
    onAdd: () => void
    onValidate: (key: LLMProviderKey) => void
    onEdit: (key: LLMProviderKey) => void
    onDelete: (key: LLMProviderKey) => void
}

export function QuillLLMProviderKeysSettings({
    isLoading,
    providerKeys,
    validatingKeyId,
    restrictionReason,
    onAdd,
    onValidate,
    onEdit,
    onDelete,
}: QuillLLMProviderKeysSettingsProps): JSX.Element {
    const columns: DataTableProps<LLMProviderKey, unknown>['columns'] = [
        {
            id: 'name',
            header: 'Name',
            enableSorting: false,
            cell: ({ row }) => {
                const key = row.original

                return (
                    <div className="flex items-center gap-2">
                        <IconKey className="shrink-0 text-muted-foreground" />
                        <div className="flex flex-col">
                            <Text size="xs" weight="medium" render={<span />}>
                                {key.name}
                            </Text>
                            {key.error_message && (key.state === 'invalid' || key.state === 'error') && (
                                <Text size="xs" variant="destructive" render={<span />}>
                                    {key.error_message}
                                </Text>
                            )}
                        </div>
                    </div>
                )
            },
        },
        {
            id: 'provider',
            header: 'Provider',
            enableSorting: false,
            cell: ({ row }) => (
                <span className="flex items-center gap-1.5">
                    <LLMProviderIcon provider={row.original.provider} />
                    <span>{LLM_PROVIDER_LABELS[row.original.provider]}</span>
                </span>
            ),
        },
        {
            id: 'api_key_masked',
            header: 'Key',
            enableSorting: false,
            cell: ({ row }) => <code className="font-mono">{row.original.api_key_masked}</code>,
        },
        {
            id: 'state',
            header: 'State',
            enableSorting: false,
            cell: ({ row }) => <QuillStateBadge state={row.original.state} errorMessage={row.original.error_message} />,
        },
        {
            id: 'last_used_at',
            header: 'Last used',
            enableSorting: false,
            cell: ({ row }) => (
                <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                    {formatProviderKeyDate(row.original.last_used_at)}
                </Text>
            ),
        },
        {
            id: 'created_at',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => {
                const key = row.original

                return (
                    <div className="flex flex-col">
                        <Text size="xs" render={<span className="whitespace-nowrap" />}>
                            {formatProviderKeyDate(key.created_at)}
                        </Text>
                        {key.created_by && (
                            <Text size="xs" variant="muted" render={<span />}>
                                by {key.created_by.first_name || key.created_by.email}
                            </Text>
                        )}
                    </div>
                )
            },
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => {
                const key = row.original

                return (
                    <div className="flex justify-end gap-1">
                        <Button
                            variant="outline"
                            loading={validatingKeyId === key.id}
                            onClick={() => onValidate(key)}
                            disabledReason={restrictionReason}
                        >
                            <IconRefresh />
                            Validate
                        </Button>
                        <Button variant="outline" onClick={() => onEdit(key)} disabledReason={restrictionReason}>
                            Edit
                        </Button>
                        <Button
                            variant="destructive-outline"
                            size="icon"
                            aria-label="Delete key"
                            tooltip="Delete key"
                            onClick={() => onDelete(key)}
                            disabledReason={restrictionReason}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                )
            },
        },
    ]

    if (isLoading) {
        return <Skeleton className="h-64 w-full" />
    }

    return (
        <div className="flex flex-col gap-4">
            {restrictionReason && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            {restrictionReason} Ask a project admin to add or manage API keys on your behalf.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            <TurnedOffEvaluationsBanner />

            {providerKeys.length > 0 && (
                <div className="flex">
                    <Button variant="primary" onClick={onAdd} disabledReason={restrictionReason}>
                        <IconPlus />
                        Add API key
                    </Button>
                </div>
            )}

            {providerKeys.length === 0 ? (
                <Empty className="rounded-lg border">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconKey />
                        </EmptyMedia>
                        <EmptyTitle>No API keys configured</EmptyTitle>
                        <EmptyDescription>
                            {restrictionReason ? (
                                <>
                                    Only project admins can add API keys for AI observability.
                                    <br />
                                    Ask a project admin to add a key for evaluations and the playground.
                                </>
                            ) : (
                                <>
                                    Add your API key for AI observability features with your own account.
                                    <br />
                                    Used for evaluations and the playground.
                                </>
                            )}
                        </EmptyDescription>
                    </EmptyHeader>
                    {!restrictionReason && (
                        <EmptyContent>
                            <Button variant="primary" onClick={onAdd}>
                                <IconPlus />
                                Add API key
                            </Button>
                        </EmptyContent>
                    )}
                </Empty>
            ) : (
                <DataTable columns={columns} data={providerKeys} getRowId={(key) => key.id} />
            )}
        </div>
    )
}
