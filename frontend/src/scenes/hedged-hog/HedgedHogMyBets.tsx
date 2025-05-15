import { useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { hedgedHogLogic } from './hedgedHogLogic'

export function MyBetsContent(): JSX.Element {
    const { bets, betsLoading } = useValues(hedgedHogLogic)

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
                            return <Link to={urls.hedgedHogBet(record.bet_definition)}>{title}</Link>
                        },
                    },
                    {
                        title: 'Amount',
                        dataIndex: 'amount',
                        key: 'amount',
                        render: function RenderAmount(amount: number | string) {
                            const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount
                            return `${numAmount.toLocaleString(undefined, {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            })} Hogecoins`
                        },
                    },
                    {
                        title: 'Prediction',
                        dataIndex: 'predicted_value',
                        key: 'predicted_value',
                        render: function RenderPrediction(value: any) {
                            return value && typeof value === 'object' && 'min' in value && 'max' in value
                                ? `${Math.round(value.min)}-${Math.round(value.max)}`
                                : ''
                        },
                    },
                    {
                        title: 'Potential payout',
                        dataIndex: 'potential_payout',
                        key: 'potential_payout',
                        render: function RenderPayout(payout: number | string) {
                            const numPayout = typeof payout === 'string' ? parseFloat(payout) : payout
                            return `${numPayout.toLocaleString(undefined, {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            })} Hogecoins`
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
                        title: 'Timestamp',
                        dataIndex: 'created_at',
                        key: 'created_at',
                        render: function RenderDate(date: string) {
                            return new Date(date).toLocaleString()
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
