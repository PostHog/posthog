import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DataTableProps,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Field,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Item,
    ItemContent,
    ItemDescription,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'

import type { DevTokenApi } from '../generated/api.schemas'
import { devModeLogic, formatDuration } from '../logics/devModeLogic'

const STATUS_BADGE: Record<DevTokenApi['status'], { label: string; variant: 'success' | 'default' | 'destructive' }> = {
    live: { label: 'Live', variant: 'success' },
    expired: { label: 'Expired', variant: 'default' },
    revoked: { label: 'Revoked', variant: 'destructive' },
}

function HeaderWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

export interface QuillDevModeSettingProps {
    durationOptions: { value: number; label: string }[]
    pickedSummary: string | null
    disabledReason: string | undefined
}

export function QuillDevModeSetting({
    durationOptions,
    pickedSummary,
    disabledReason,
}: QuillDevModeSettingProps): JSX.Element {
    const {
        usage,
        usageLoading,
        minted,
        mintedLoading,
        remainingUsd,
        cliRequest,
        liveTokenCount,
        revoking,
        capUsd,
        ttlSeconds,
    } = useValues(devModeLogic)
    const { mint, revokeToken, authorizeCli, dismissCliRequest, setCapUsd, setTtlSeconds } = useActions(devModeLogic)

    const capId = 'ai-gateway-dev-mode-cap'
    const ttlId = 'ai-gateway-dev-mode-ttl'
    const tokens = usage?.tokens ?? []

    const columns: DataTableProps<DevTokenApi, unknown>['columns'] = [
        {
            id: 'created_at',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => <TZLabel time={row.original.created_at} />,
        },
        {
            id: 'expires_at',
            header: 'Expires',
            enableSorting: false,
            cell: ({ row }) => (row.original.expires_at ? <TZLabel time={row.original.expires_at} /> : null),
        },
        {
            id: 'status',
            header: 'Status',
            enableSorting: false,
            cell: ({ row }) => (
                <Badge variant={STATUS_BADGE[row.original.status].variant}>
                    {STATUS_BADGE[row.original.status].label}
                </Badge>
            ),
        },
        {
            id: 'client',
            header: 'Source',
            enableSorting: false,
            cell: ({ row }) => <Badge>{row.original.client === 'cli' ? 'CLI' : 'Web'}</Badge>,
        },
        {
            id: 'cap_usd',
            header: 'Spend limit',
            enableSorting: false,
            cell: ({ row }) => <span translate="no">${row.original.cap_usd}</span>,
        },
        {
            id: 'remaining_usd',
            header: () => (
                <HeaderWithHelp label="Left" help="Budget left on a live token, net of requests still in flight." />
            ),
            enableSorting: false,
            cell: ({ row }) =>
                row.original.status !== 'live' ? null : row.original.remaining_usd != null ? (
                    <span translate="no">${Number(row.original.remaining_usd).toFixed(4)}</span>
                ) : (
                    <Text size="xs" variant="muted" render={<span />}>
                        Unknown
                    </Text>
                ),
        },
        {
            id: 'spent_usd',
            header: () => (
                <HeaderWithHelp
                    label="Spent"
                    help="What a revoked token spent. This is what it counts against your limit."
                />
            ),
            enableSorting: false,
            cell: ({ row }) =>
                row.original.spent_usd != null ? (
                    <span translate="no">${Number(row.original.spent_usd).toFixed(4)}</span>
                ) : null,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) =>
                row.original.status === 'live' ? (
                    <Button
                        variant="destructive-outline"
                        onClick={() => revokeToken(row.original.id)}
                        loading={revoking?.id === row.original.id}
                        disabledReason={revoking ? 'Revoking' : undefined}
                    >
                        Revoke
                    </Button>
                ) : null,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            {cliRequest ? (
                <Item tone="info" size="sm" data-attr="ai-gateway-dev-mode-cli-request">
                    <ItemContent>
                        <ItemDescription>
                            <code>hogli gateway:token</code> is asking for a token
                            {pickedSummary ? ` (${pickedSummary}, change it below)` : ''}. Approve only if you just ran
                            that command.
                        </ItemDescription>
                        <div className="flex flex-wrap gap-2">
                            <Button variant="primary" onClick={authorizeCli} disabledReason={disabledReason}>
                                Approve
                            </Button>
                            <Button variant="outline" onClick={dismissCliRequest}>
                                Deny
                            </Button>
                        </div>
                    </ItemContent>
                </Item>
            ) : null}

            <Text size="xs" render={<p className="m-0" />}>
                Pick how much a token can spend (${usage?.token_cap_min_usd ?? '…'} to ${usage?.token_cap_usd ?? '…'})
                and how long it lasts (up to {usage ? formatDuration(usage.ttl_max_seconds) : '…'}).
            </Text>

            <div className="flex flex-wrap items-end gap-2">
                <Field className="w-32">
                    <FieldLabel htmlFor={capId}>Spend limit</FieldLabel>
                    <InputGroup>
                        <InputGroupAddon align="inline-start">
                            <InputGroupText>$</InputGroupText>
                        </InputGroupAddon>
                        <InputGroupInput
                            id={capId}
                            type="number"
                            min={usage ? Number(usage.token_cap_min_usd) : undefined}
                            max={usage ? Number(usage.token_cap_usd) : undefined}
                            step={1}
                            value={capUsd ?? ''}
                            onChange={(event) =>
                                setCapUsd(event.target.value === '' ? null : Number(event.target.value))
                            }
                            data-attr="ai-gateway-dev-mode-cap"
                        />
                    </InputGroup>
                </Field>
                <Field className="w-fit">
                    <FieldLabel htmlFor={ttlId}>Expires after</FieldLabel>
                    <Select
                        value={ttlSeconds}
                        onValueChange={(value) => value !== null && setTtlSeconds(value as number)}
                    >
                        <SelectTrigger id={ttlId} className="min-w-32" data-attr="ai-gateway-dev-mode-ttl">
                            <SelectValue>
                                {(seconds: number | null) =>
                                    durationOptions.find((option) => option.value === seconds)?.label
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {durationOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>
                <Button
                    variant="primary"
                    onClick={mint}
                    loading={mintedLoading}
                    disabledReason={disabledReason}
                    data-attr="ai-gateway-dev-mode-mint"
                >
                    Create token
                </Button>
                {usage ? (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        <span translate="no">
                            ${remainingUsd?.toFixed(2)} of ${usage.daily_cap_usd}
                        </span>{' '}
                        left. Tokens count against it until they expire, and for at least 24 hours.
                    </Text>
                ) : null}
            </div>

            {minted ? (
                <div className="flex flex-col gap-2">
                    <Item tone="success" size="sm">
                        <ItemContent>
                            <ItemDescription>Copy this token now. It won't be shown again.</ItemDescription>
                        </ItemContent>
                    </Item>
                    <CodeSnippet className="ph-no-capture" language={Language.Text} wrap thing="token">
                        {minted.token}
                    </CodeSnippet>
                </div>
            ) : null}

            {usageLoading && tokens.length === 0 ? (
                <Skeleton className="h-24" />
            ) : (
                <div aria-busy={usageLoading}>
                    <DataTable
                        columns={columns}
                        data={tokens}
                        fullWidth
                        getRowId={(token) => token.id}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No unexpired tokens, and none created in the last 24 hours</EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}
            {liveTokenCount > 1 ? (
                <div>
                    <Button
                        variant="destructive-outline"
                        onClick={() => revokeToken(null)}
                        loading={revoking?.id === null}
                        disabledReason={revoking ? 'Revoking' : undefined}
                    >
                        Revoke all
                    </Button>
                </div>
            ) : null}
        </div>
    )
}
