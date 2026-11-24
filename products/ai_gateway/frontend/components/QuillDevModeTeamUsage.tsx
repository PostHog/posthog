import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import {
    Badge,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
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
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { PAGE_SIZE_OPTIONS, devModeTeamUsageLogic } from '../logics/devModeTeamUsageLogic'
import { ACTIVITY_TAG, usd } from './DevModeTeamUsage'

const BADGE_VARIANT = { success: 'success', danger: 'destructive', default: 'default' } as const

function EmptyRows({ children }: { children: string }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyDescription>{children}</EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}

export function QuillDevModeTeamUsage(): JSX.Element {
    const { teamUsageLoading, teamUsage, refusal, isPayingTeam, search, pageSize, filteredUsers, filteredActivity } =
        useValues(devModeTeamUsageLogic)
    const { setSearch, setPageSize } = useActions(devModeTeamUsageLogic)

    if (refusal && !teamUsage) {
        return (
            <Item tone="warning" size="sm">
                <ItemContent>
                    <ItemDescription>{refusal}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    if (teamUsage && !isPayingTeam) {
        return (
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        {`Developer mode is billed to project ${teamUsage.paying_team_id}. Switch to that project to see team usage and activity.`}
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                Spend is settled gateway cost for calls made with developer mode tokens. Reserved is what counts against
                each user's limit: what revoked tokens spent, and the full cap of every other token minted in the last
                24 hours or not yet expired.
            </Text>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <InputGroup size="sm" className="max-w-80 flex-1">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search by email"
                        aria-label="Search by email"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                </InputGroup>
                <Select<number> value={pageSize} onValueChange={(value) => value !== null && setPageSize(value)}>
                    <SelectTrigger aria-label="Rows per page">
                        <SelectValue>{(size: number) => `Show ${size}`}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {PAGE_SIZE_OPTIONS.map((size) => (
                            <SelectItem key={size} value={size}>
                                {`Show ${size}`}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
            {teamUsageLoading && !teamUsage ? (
                <Skeleton className="h-32 w-full" />
            ) : (
                <DataTable
                    size="sm"
                    fullWidth
                    data={filteredUsers}
                    pageSize={pageSize}
                    getRowId={(row) => row.distinct_id}
                    empty={
                        <EmptyRows>
                            {search
                                ? 'No users match this search'
                                : 'No developer mode tokens or spend in the last 30 days'}
                        </EmptyRows>
                    }
                    columns={[
                        {
                            id: 'email',
                            header: 'User',
                            enableSorting: false,
                            meta: { expand: true },
                            cell: ({ row }) =>
                                row.original.email ?? (
                                    <Text size="xs" variant="muted" render={<span />} translate="no">
                                        {`Unknown user (${row.original.distinct_id})`}
                                    </Text>
                                ),
                        },
                        {
                            id: 'spend_usd_24h',
                            header: 'Spend 24h',
                            accessorFn: (row) => Number(row.spend_usd_24h),
                            cell: ({ row }) => usd(row.original.spend_usd_24h),
                        },
                        {
                            id: 'spend_usd_7d',
                            header: 'Spend 7d',
                            accessorFn: (row) => Number(row.spend_usd_7d),
                            cell: ({ row }) => usd(row.original.spend_usd_7d),
                        },
                        {
                            id: 'spend_usd_30d',
                            header: 'Spend 30d',
                            accessorFn: (row) => Number(row.spend_usd_30d),
                            cell: ({ row }) => usd(row.original.spend_usd_30d),
                        },
                        {
                            id: 'reserved_usd_24h',
                            header: 'Reserved 24h',
                            enableSorting: false,
                            cell: ({ row }) => usd(row.original.reserved_usd_24h),
                        },
                        {
                            id: 'tokens_minted_30d',
                            header: 'Tokens 24h / 30d',
                            accessorFn: (row) => row.tokens_minted_30d,
                            cell: ({ row }) => (
                                <span translate="no">
                                    {`${row.original.tokens_minted_24h} / ${row.original.tokens_minted_30d}`}
                                </span>
                            ),
                        },
                        {
                            id: 'live_tokens',
                            header: 'Live',
                            enableSorting: false,
                            cell: ({ row }) => row.original.live_tokens,
                        },
                        {
                            id: 'revoked_30d',
                            header: 'Revoked 30d',
                            enableSorting: false,
                            cell: ({ row }) => row.original.revoked_30d,
                        },
                        {
                            id: 'last_minted_at',
                            header: 'Last minted',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.last_minted_at ? <TZLabel time={row.original.last_minted_at} /> : null,
                        },
                    ]}
                />
            )}
            <Heading size="sm" render={<h3 className="m-0" />}>
                Activity
            </Heading>
            {teamUsageLoading && !teamUsage ? (
                <Skeleton className="h-32 w-full" />
            ) : (
                <DataTable
                    size="sm"
                    fullWidth
                    data={filteredActivity}
                    pageSize={pageSize}
                    empty={
                        <EmptyRows>
                            {search ? 'No activity matches this search' : 'No mints or revokes in the last 30 days'}
                        </EmptyRows>
                    }
                    columns={[
                        {
                            id: 'at',
                            header: 'When',
                            enableSorting: false,
                            cell: ({ row }) => <TZLabel time={row.original.at} />,
                        },
                        {
                            id: 'activity',
                            header: 'Action',
                            enableSorting: false,
                            cell: ({ row }) => {
                                const tag = ACTIVITY_TAG[row.original.activity] ?? {
                                    label: row.original.activity,
                                    type: 'default',
                                }
                                return <Badge variant={BADGE_VARIANT[tag.type]}>{tag.label}</Badge>
                            },
                        },
                        {
                            id: 'owner_email',
                            header: 'Token owner',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.owner_email ?? (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Unknown
                                    </Text>
                                ),
                        },
                        {
                            id: 'actor_email',
                            header: 'By',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.actor_email && row.original.actor_email !== row.original.owner_email ? (
                                    row.original.actor_email
                                ) : (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Owner
                                    </Text>
                                ),
                        },
                        {
                            id: 'client',
                            header: 'Source',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.client ? (
                                    <Badge>{row.original.client === 'cli' ? 'CLI' : 'Web'}</Badge>
                                ) : null,
                        },
                        {
                            id: 'cap_usd',
                            header: 'Spend limit',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.cap_usd ? <span translate="no">{`$${row.original.cap_usd}`}</span> : null,
                        },
                    ]}
                />
            )}
        </div>
    )
}
