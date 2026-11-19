import { useValues } from 'kea'

import { LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'

import { GatewayKeySpendRow, gatewayKeySpendLogic } from './gatewayKeySpendLogic'
import { GATEWAY_SPEND_WINDOW_DAYS } from './gatewayKeySpendQuery'

export function GatewayKeySpend(): JSX.Element | null {
    const { hasGatewayKeys, summary, spend, spendLoading, spendFailed } = useValues(gatewayKeySpendLogic)

    if (!hasGatewayKeys) {
        return null
    }

    const loading = spendLoading || spend === null

    return (
        <div className="mt-6">
            <h3>AI gateway spend by key</h3>
            <p className="text-secondary">
                Spend on gateway generations in the last {GATEWAY_SPEND_WINDOW_DAYS} days, grouped by the key that made
                them.
            </p>
            {spendFailed ? (
                <p className="text-danger">Couldn't load gateway spend. Reload the page to try again.</p>
            ) : (
                <LemonTable<GatewayKeySpendRow>
                    dataSource={summary.rows}
                    loading={loading}
                    rowKey="id"
                    size="small"
                    columns={[
                        {
                            title: 'Label',
                            dataIndex: 'label',
                            render: (_, row) => <span className="font-semibold">{row.label}</span>,
                        },
                        {
                            title: 'Secret key',
                            dataIndex: 'maskValue',
                            render: (_, row) =>
                                row.maskValue ? (
                                    <span className="font-mono">{row.maskValue}</span>
                                ) : (
                                    <span className="text-secondary">No preview</span>
                                ),
                        },
                        {
                            title: 'Requests',
                            dataIndex: 'requests',
                            render: (_, row) => humanFriendlyNumber(row.requests),
                            sorter: (a, b) => a.requests - b.requests,
                        },
                        {
                            title: 'Spend',
                            dataIndex: 'costUsd',
                            render: (_, row) => humanFriendlyCurrency(row.costUsd, 4),
                            sorter: (a, b) => a.costUsd - b.costUsd,
                        },
                    ]}
                />
            )}
            {!loading && !spendFailed && (summary.unmatchedCostUsd > 0 || summary.untaggedCostUsd > 0) && (
                <p className="text-secondary text-sm mt-2 mb-0 flex flex-wrap gap-x-3">
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
                </p>
            )}
        </div>
    )
}
