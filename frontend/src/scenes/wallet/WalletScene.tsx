import { LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag, lemonToast } from "@posthog/lemon-ui";
import dayjs from "dayjs";
import { IconArrowUp } from "lib/lemon-ui/icons";
import { useActions, useValues } from "kea";
import { IconArrowDown } from "lib/lemon-ui/icons";
import { SceneExport } from "scenes/sceneTypes";
import { userLogic } from "scenes/userLogic";
import { walletLogic } from "scenes/wallet/walletLogic";
import { ProductIntroduction } from "lib/components/ProductIntroduction/ProductIntroduction";
import { ProductKey } from "~/types";
import { BurningMoneyHog } from "lib/components/hedgehogs";

export const scene: SceneExport = {
    component: WalletScene,
    logic: walletLogic,
}

export function WalletScene(): JSX.Element {
    const { transactions, transactionsLoading, balance, isInitialized, walletStateLoading } =
        useValues(walletLogic)
    const { initializeWallet } = useActions(walletLogic)
    const { user } = useValues(userLogic)

    const transactionList = transactions.results
    return (
        <div className="mt-4">
            {isInitialized ? (
                <div className="mb-8">
                    <div className="flex items-start justify-between gap-6">
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div style={{ width: '400px' }}>
                            <LemonCard className="p-0 overflow-hidden shadow-xl rounded-xl border-0">
                                <div
                                    className="p-6 text-white relative"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        background: 'linear-gradient(135deg, #5042BC 0%, #8E5AE8 100%)',
                                        borderRadius: '12px',
                                    }}
                                >
                                    {/* Card logo */}
                                    <div className="flex justify-between items-center mb-6">
                                        {/* <img src={hogecoin} alt="Hogecoin" className="h-16 w-auto" /> */}
                                        <img
                                            src="/static/posthog-logo.svg"
                                            alt="PostHog"
                                            className="h-8 w-auto"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ filter: 'brightness(0) invert(1)' }}
                                        />
                                    </div>

                                    {/* Balance display */}
                                    <div className="mb-6">
                                        <div className="text-sm font-medium opacity-80 mb-1">Available Balance</div>
                                        {walletStateLoading || transactionsLoading ? (
                                            <LemonSkeleton className="h-12 w-32" />
                                        ) : (
                                            <div className="text-4xl font-bold">
                                                {balance.toLocaleString()} Hogecoins
                                            </div>
                                        )}
                                    </div>

                                    {/* Card holder name */}
                                    <div className="flex justify-between items-end">
                                        <div>
                                            <div className="text-xs uppercase opacity-70 mb-1">CARD HOLDER</div>
                                            <div className="font-medium">
                                                {user?.first_name} {user?.last_name}
                                            </div>
                                        </div>
                                    </div>

                                    {/* Decorative elements */}
                                    <div
                                        className="absolute top-0 right-0 w-64 h-64 rounded-full"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            background:
                                                'radial-gradient(circle, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 70%)',
                                            transform: 'translate(30%, -30%)',
                                        }}
                                    />
                                    <div
                                        className="absolute bottom-0 left-0 w-40 h-40 rounded-full"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            background:
                                                'radial-gradient(circle, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0) 70%)',
                                            transform: 'translate(-30%, 30%)',
                                        }}
                                    />
                                </div>
                            </LemonCard>
                        </div>

                        {/* Action button - positioned beside the card */}
                        <div className="flex justify-end items-start">
                        </div>
                    </div>
                </div>
            ) : (
                <ProductIntroduction
                    productName="Wallet"
                    productKey={ProductKey.WALLET}
                    thingName="Wallet"
                    description="Get rich with the PostHog wallet."
                    isEmpty={true}
                    customHog={BurningMoneyHog}
                    action={() => initializeWallet()}
                />
            )}

            <div className="mb-8">
                <h3 className="mb-4">Transaction History</h3>
                {transactionsLoading ? (
                    <LemonSkeleton className="h-40" />
                ) : transactionList.length === 0 ? (
                    <LemonCard className="p-6 text-center">
                        <p className="text-muted">No transactions yet</p>
                    </LemonCard>
                ) : (
                    <LemonTable
                        dataSource={transactionList}
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
                                title: 'Source',
                                render: function RenderSource(_, transaction) {
                                    const transaction_type = transaction.transaction_type
                                    let source = ''

                                    if (transaction_type === 'initialization') {
                                        source = 'Capital Account'
                                    } else if (transaction_type === 'reward') {
                                        source = 'Rewards Pool'
                                    } else if (transaction_type === 'redemption') {
                                        source = 'Your Wallet'
                                    } else if (transaction_type === 'refund') {
                                        source = 'System Account'
                                    } else if (transaction_type === 'expiry') {
                                        source = 'Your Wallet'
                                    } else if (transaction_type === 'adjustment') {
                                        source = 'System Account'
                                    }

                                    return <span className="text-muted">{source}</span>
                                },
                            },
                            {
                                title: 'Destination',
                                render: function RenderDestination(_, transaction) {
                                    const transaction_type = transaction.transaction_type
                                    let destination = ''

                                    if (transaction_type === 'initialization') {
                                        destination = 'Your Wallet'
                                    } else if (transaction_type === 'reward') {
                                        destination = 'Your Wallet'
                                    } else if (transaction_type === 'redemption') {
                                        destination = 'Hoggy Bank'
                                    } else if (transaction_type === 'refund') {
                                        destination = 'Your Wallet'
                                    } else if (transaction_type === 'expiry') {
                                        destination = 'Hoggy Bank'
                                    } else if (transaction_type === 'adjustment') {
                                        destination = 'Your Wallet'
                                    }

                                    return <span className="text-muted">{destination}</span>
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
                                            <span>
                                                {isIncoming ? '+' : isOutgoing ? '-' : ''}
                                                {parseFloat(amount?.toString() || '0').toLocaleString()} Hogecoins
                                            </span>
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
