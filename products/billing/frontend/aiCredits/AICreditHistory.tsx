import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AICreditHistoryEntryApi } from 'products/billing/frontend/generated/api.schemas'

import { aiCreditsLogic } from './aiCreditsLogic'

export function AICreditHistory(): JSX.Element {
    const { history, historyLoading } = useValues(aiCreditsLogic)
    const { loadOlderHistory } = useActions(aiCreditsLogic)

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">History</h3>
            <LemonTable<AICreditHistoryEntryApi>
                dataSource={history?.results ?? []}
                loading={historyLoading}
                emptyState="No purchases or reloads yet"
                rowKey={(entry) => `${entry.created_at}-${entry.kind}-${entry.total_usd}`}
                columns={[
                    {
                        title: 'Date',
                        key: 'created_at',
                        render: (_, entry) => <TZLabel time={entry.created_at} />,
                    },
                    {
                        title: 'Type',
                        key: 'kind',
                        render: (_, entry) => (entry.kind === 'automatic_reload' ? 'Automatic reload' : 'Purchase'),
                    },
                    {
                        title: 'Credits',
                        key: 'amount_usd',
                        align: 'right',
                        render: (_, entry) => humanFriendlyCurrency(entry.amount_usd),
                    },
                    {
                        title: 'Tax',
                        key: 'tax_usd',
                        align: 'right',
                        render: (_, entry) => humanFriendlyCurrency(entry.tax_usd),
                    },
                    {
                        title: 'Total',
                        key: 'total_usd',
                        align: 'right',
                        render: (_, entry) => humanFriendlyCurrency(entry.total_usd),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, entry) =>
                            entry.status === 'added' ? (
                                <LemonTag type="success">Added</LemonTag>
                            ) : (
                                <LemonTag type="warning">Pending</LemonTag>
                            ),
                    },
                    {
                        title: 'Receipt',
                        key: 'receipt_url',
                        align: 'right',
                        render: (_, entry) =>
                            entry.receipt_url ? (
                                <Link to={entry.receipt_url} target="_blank">
                                    View
                                </Link>
                            ) : null,
                    },
                ]}
            />
            {history?.has_more && (
                <div>
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
