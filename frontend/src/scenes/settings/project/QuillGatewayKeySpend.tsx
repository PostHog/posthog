import type { ColumnDef } from '@tanstack/react-table'

import { DataTable, Heading, Skeleton, Text } from '@posthog/quill'

import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'

import { GatewayKeySpendRow, GatewayKeySpendSummary } from './gatewayKeySpendLogic'
import { GATEWAY_SPEND_WINDOW_DAYS } from './gatewayKeySpendQuery'

const COLUMNS: ColumnDef<GatewayKeySpendRow>[] = [
    {
        id: 'label',
        header: 'Label',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => <span className="font-semibold">{row.original.label}</span>,
    },
    {
        id: 'maskValue',
        header: 'Secret key',
        enableSorting: false,
        cell: ({ row }) =>
            row.original.maskValue ? (
                <span className="font-mono">{row.original.maskValue}</span>
            ) : (
                <span className="text-muted-foreground">No preview</span>
            ),
    },
    {
        id: 'requests',
        header: 'Requests',
        accessorFn: (row) => row.requests,
        cell: ({ row }) => <span translate="no">{humanFriendlyNumber(row.original.requests)}</span>,
    },
    {
        id: 'costUsd',
        header: 'Spend',
        accessorFn: (row) => row.costUsd,
        cell: ({ row }) => <span translate="no">{humanFriendlyCurrency(row.original.costUsd, 4)}</span>,
    },
]

export function QuillGatewayKeySpend({
    summary,
    loading,
    spendFailed,
}: {
    summary: GatewayKeySpendSummary
    loading: boolean
    spendFailed: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                AI gateway spend by key
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Spend on gateway generations in the last {GATEWAY_SPEND_WINDOW_DAYS} days, grouped by the key that made
                them.
            </Text>
            {spendFailed ? (
                <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                    Couldn't load gateway spend. Reload the page to try again.
                </Text>
            ) : loading ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <DataTable columns={COLUMNS} data={summary.rows} fullWidth size="sm" getRowId={(row) => row.id} />
            )}
            {!loading && !spendFailed && (summary.unmatchedCostUsd > 0 || summary.untaggedCostUsd > 0) && (
                <Text size="xs" variant="muted" render={<p className="m-0 flex flex-wrap gap-x-3" />}>
                    {summary.unmatchedCostUsd > 0 && (
                        <span>
                            Rolled or deleted keys:{' '}
                            <span translate="no">{humanFriendlyCurrency(summary.unmatchedCostUsd, 4)}</span>
                        </span>
                    )}
                    {summary.untaggedCostUsd > 0 && (
                        <span>
                            Before keys were attributed:{' '}
                            <span translate="no">{humanFriendlyCurrency(summary.untaggedCostUsd, 4)}</span>
                        </span>
                    )}
                </Text>
            )}
        </div>
    )
}
