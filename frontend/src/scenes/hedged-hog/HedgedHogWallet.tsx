import { IconCreditCard } from '@posthog/icons'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconArrowDown, IconArrowUp, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { hedgedHogLogic } from './hedgedHogLogic'

export const WalletContent = (): JSX.Element => {
    const { transactions, transactionsLoading, walletBalance, walletBalanceLoading, isOnboarded } =
        useValues(hedgedHogLogic)

    return (
        <div className="mt-4">
            {isOnboarded && (
                <div className="mb-8">
                    <LemonCard className="bg-gradient-to-br from-primary to-primary-3000 text-white p-6">
                        <div className="flex items-center mb-4">
                            <IconCreditCard className="text-2xl mr-2" />
                            <h3 className="text-white m-0">Wallet Balance</h3>
                        </div>
                        <div className="mb-6">
                            {walletBalanceLoading ? (
                                <LemonSkeleton className="h-12 w-32" />
                            ) : (
                                <div className="text-4xl font-bold">{walletBalance} Hedgies</div>
                            )}
                        </div>
                        <div className="text-sm opacity-80">Use your Hedgies to place bets on metrics</div>
                    </LemonCard>
                </div>
            )}

            <div className="mb-8">
                <h3 className="mb-4">Transaction History</h3>
                {transactionsLoading ? (
                    <LemonSkeleton className="h-40" />
                ) : transactions.length === 0 ? (
                    <LemonCard className="p-6 text-center">
                        <p className="text-muted">No transactions yet</p>
                    </LemonCard>
                ) : (
                    <LemonTable
                        dataSource={transactions}
                        columns={[
                            {
                                title: 'Date',
                                dataIndex: 'created_at',
                                render: function RenderDate(_, transaction) {
                                    const created_at = transaction.created_at
                                    return dayjs(created_at).format('MMM D, YYYY [at] h:mm A')
                                },
                            },
                            {
                                title: 'Type',
                                dataIndex: 'transaction_type',
                                render: function RenderType(_, transaction) {
                                    const transaction_type = transaction.transaction_type
                                    let color = 'default'
                                    let icon = null

                                    if (transaction_type === 'onboarding') {
                                        color = 'success'
                                    } else if (transaction_type === 'bet_place') {
                                        color = 'warning'
                                        icon = <IconArrowDown />
                                    } else if (transaction_type === 'bet_win') {
                                        color = 'success'
                                        icon = <IconArrowUp />
                                    }

                                    return (
                                        <LemonTag icon={icon || undefined} color={color} className="capitalize">
                                            {transaction_type?.replace('_', ' ')}
                                        </LemonTag>
                                    )
                                },
                            },
                            {
                                title: 'Source -> Destination',
                                render: function RenderSourceDest(_, transaction) {
                                    const transaction_type = transaction.transaction_type
                                    let source = ''
                                    let destination = ''

                                    if (transaction_type === 'onboarding') {
                                        source = 'Hoggy Bank'
                                        destination = 'Your Wallet'
                                    } else if (transaction_type === 'bet_place') {
                                        source = 'Your Wallet'
                                        destination = 'Pool'
                                    } else if (transaction_type === 'bet_win') {
                                        source = 'Pool'
                                        destination = 'Your Wallet'
                                    } else if (transaction_type === 'deposit') {
                                        source = 'Stripe'
                                        destination = 'Your Wallet'
                                    }

                                    return (
                                        <div className="flex items-center gap-2">
                                            <span className="text-muted">{source}</span>
                                            <IconChevronRight className="text-muted" />
                                            <span className="text-muted">{destination}</span>
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Amount',
                                dataIndex: 'amount',
                                render: function RenderAmount(_, transaction) {
                                    const amount = transaction.amount
                                    const isDebit = transaction.entry_type === 'debit'
                                    const isIncoming =
                                        isDebit &&
                                        (transaction.transaction_type === 'onboarding' ||
                                            transaction.transaction_type === 'bet_win')
                                    const isOutgoing = isDebit && transaction.transaction_type === 'bet_place'

                                    return (
                                        <span
                                            className={`font-semibold ${
                                                isIncoming ? 'text-success' : isOutgoing ? 'text-danger' : ''
                                            }`}
                                        >
                                            {isIncoming ? '+' : isOutgoing ? '-' : ''}
                                            {parseFloat(amount?.toString() || '0').toLocaleString()} Hedgies
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Description',
                                dataIndex: 'description',
                                render: function RenderDescription(description) {
                                    return <span className="text-sm">{description}</span>
                                },
                            },
                        ]}
                        rowKey="id"
                    />
                )}
            </div>
        </div>
    )
}
