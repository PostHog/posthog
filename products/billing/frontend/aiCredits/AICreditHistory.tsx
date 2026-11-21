import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type {
    AICreditHistoryEntryApi,
    AICreditInProgressEntryApi,
} from 'products/billing/frontend/generated/api.schemas'

import { aiCreditsLogic } from './aiCreditsLogic'

type HistoryRow = AICreditHistoryEntryApi | AICreditInProgressEntryApi

function isInProgress(row: HistoryRow): row is AICreditInProgressEntryApi {
    return row.status === 'processing'
}

function StatusTag({ row }: { row: HistoryRow }): JSX.Element {
    if (isInProgress(row)) {
        return <LemonTag type="muted">Processing</LemonTag>
    }
    return row.status === 'added' ? (
        <LemonTag type="success">Added</LemonTag>
    ) : (
        <LemonTag type="warning">Pending</LemonTag>
    )
}

export function AICreditHistory(): JSX.Element {
    const { history, historyLoading } = useValues(aiCreditsLogic)
    const { loadOlderHistory } = useActions(aiCreditsLogic)

    return (
        <div className="rounded border bg-surface-primary">
            <h3 className="m-0 border-b px-5 py-3.5 text-base font-semibold">History</h3>
            <LemonTable<HistoryRow>
                embedded
                dataSource={[...(history?.in_progress ?? []), ...(history?.results ?? [])]}
                loading={historyLoading}
                emptyState="No purchases or reloads yet. Credits you add show here."
                rowKey={(entry) =>
                    isInProgress(entry) ? entry.idempotency_key : `${entry.created_at}-${entry.kind}-${entry.total_usd}`
                }
                columns={[
                    {
                        title: 'Date',
                        key: 'created_at',
                        render: (_, entry) => (
                            <span className="text-secondary">{dayjs(entry.created_at).format('MMM D, HH:mm')}</span>
                        ),
                    },
                    {
                        title: 'Type',
                        key: 'kind',
                        render: (_, entry) => (
                            <span className="font-medium">
                                {!isInProgress(entry) && entry.kind === 'automatic_reload'
                                    ? 'Automatic reload'
                                    : 'Purchase'}
                            </span>
                        ),
                    },
                    {
                        title: 'Amount',
                        key: 'amount_usd',
                        align: 'right',
                        render: (_, entry) => (
                            <span className="font-semibold">{humanFriendlyCurrency(entry.amount_usd)}</span>
                        ),
                    },
                    {
                        title: 'Tax',
                        key: 'tax_usd',
                        align: 'right',
                        render: (_, entry) => (
                            <span className="text-secondary">{humanFriendlyCurrency(entry.tax_usd)}</span>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, entry) => <StatusTag row={entry} />,
                    },
                    {
                        title: 'Receipt',
                        key: 'receipt_url',
                        align: 'right',
                        render: (_, entry) =>
                            !isInProgress(entry) && entry.receipt_url ? (
                                <Link to={entry.receipt_url} target="_blank" className="font-medium">
                                    View
                                </Link>
                            ) : null,
                    },
                ]}
            />
            {history?.has_more && (
                <div className="border-t px-5 py-3">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={loadOlderHistory}
                        loading={historyLoading}
                        data-attr="ai-credits-older-history"
                    >
                        Show older
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
