import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { hedgedHogLogic } from './hedgedHogLogic'

export function MyBetsContent(): JSX.Element {
    const { bets, betsLoading } = useValues(hedgedHogLogic)
    const { push } = useActions(router)

    return (
        <div className="space-y-4">
            <h2 className="text-xl">My Bets</h2>
            <LemonTable
                dataSource={bets || []}
                columns={[
                    {
                        title: 'Bet',
                        dataIndex: 'bet_definition_title',
                        key: 'bet_definition_title',
                        render: function RenderBetTitle(title: string, record: any) {
                            return (
                                <LemonButton
                                    type="secondary"
                                    onClick={() => push(urls.hedgedHogBet(record.bet_definition))}
                                >
                                    {title}
                                </LemonButton>
                            )
                        },
                    },
                    {
                        title: 'Amount',
                        dataIndex: 'amount',
                        key: 'amount',
                        render: function RenderAmount(amount: number | string) {
                            const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount
                            return `${numAmount.toFixed(2)} Hogecoins`
                        },
                    },
                    {
                        title: 'Prediction',
                        dataIndex: 'predicted_value',
                        key: 'predicted_value',
                        render: function RenderPrediction(value: any) {
                            const prediction = typeof value === 'object' ? value.value : value
                            return prediction === 1 ? 'Yes' : 'No'
                        },
                    },
                    {
                        title: 'Potential Payout',
                        dataIndex: 'potential_payout',
                        key: 'potential_payout',
                        render: function RenderPayout(payout: number | string) {
                            const numPayout = typeof payout === 'string' ? parseFloat(payout) : payout
                            return `${numPayout.toFixed(2)} Hogecoins`
                        },
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        key: 'status',
                        render: function RenderStatus(status: string) {
                            const statusColors = {
                                ACTIVE: 'text-warning',
                                WON: 'text-success',
                                LOST: 'text-danger',
                                SETTLED: 'text-muted',
                            }
                            return <span className={statusColors[status as keyof typeof statusColors]}>{status}</span>
                        },
                    },
                    {
                        title: 'Created',
                        dataIndex: 'created_at',
                        key: 'created_at',
                        render: function RenderDate(date: string) {
                            return new Date(date).toLocaleDateString()
                        },
                    },
                ]}
                rowKey="id"
                embedded
                nouns={['bet', 'bets']}
                emptyState="No bets placed yet"
                loading={betsLoading}
            />
        </div>
    )
}
