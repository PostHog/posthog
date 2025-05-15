import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'

import { hedgedHogBetDefinitionsLogic } from './hedgedHogBetDefinitionsLogic'
import { hedgedHogLogic } from './hedgedHogLogic'

interface BetFlowProps {
    amount: number
    setAmount: (amount: number) => void
    betType: string
    setBetType: (type: string) => void
    showConfirmation: boolean
    setShowConfirmation: (show: boolean) => void
    handlePlaceBet: () => void
}

const BetFlow = ({
    amount,
    setAmount,
    betType,
    setBetType,
    showConfirmation,
    setShowConfirmation,
    handlePlaceBet,
}: BetFlowProps): JSX.Element => {
    return (
        <LemonCard className="h-full">
            <div className="p-4">
                {!showConfirmation ? (
                    <div className="space-y-6">
                        <div>
                            <h3 className="text-lg font-semibold mb-4">Place Your Bet</h3>
                            <div className="space-y-3">
                                <LemonButton
                                    fullWidth
                                    center
                                    type="primary"
                                    onClick={() => {
                                        setBetType('Yes')
                                        setShowConfirmation(true)
                                    }}
                                    disabledReason={amount === 0 && 'The amount must be greater than 0'}
                                    className="h-12 text-lg"
                                >
                                    Yes 39¢
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    center
                                    type="primary"
                                    onClick={() => {
                                        setBetType('No')
                                        setShowConfirmation(true)
                                    }}
                                    disabledReason={amount === 0 && 'The amount must be greater than 0'}
                                    className="h-12 text-lg"
                                >
                                    No 62¢
                                </LemonButton>
                            </div>
                        </div>

                        <div>
                            <h3 className="font-semibold mb-2">Amount</h3>
                            <div className="relative">
                                <LemonInput
                                    className="text-2xl font-bold"
                                    type="text"
                                    prefix={<span className="text-muted">$</span>}
                                    value={amount.toString()}
                                    onChange={(value) => setAmount(Number(value) || 0)}
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-3 gap-2">
                            {['+$1', '+$20', '+$100'].map((amt) => (
                                <LemonButton
                                    key={amt}
                                    type="secondary"
                                    className="text-center"
                                    onClick={() => setAmount(Number(amount + Number(amt.replace('+$', ''))))}
                                >
                                    {amt}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="bg-bg-light rounded-lg p-6 border">
                        <h3 className="font-semibold text-lg mb-6">Confirm Your Bet</h3>

                        <div className="space-y-4 mb-8">
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Bet Type:</span>
                                <span
                                    className={`text-lg font-semibold ${
                                        betType === 'Yes' ? 'text-success' : 'text-danger'
                                    }`}
                                >
                                    {betType}
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Amount:</span>
                                <span className="text-lg font-semibold">${amount.toFixed(2)}</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Price:</span>
                                <span className="text-lg font-semibold">{betType === 'Yes' ? '39¢' : '62¢'}</span>
                            </div>
                            <LemonDivider className="my-4" />
                            <div className="flex justify-between items-center">
                                <span className="font-semibold">Potential Payout:</span>
                                <span className="text-success text-lg font-bold">
                                    ${betType === 'Yes' ? (amount / 0.39).toFixed(2) : (amount / 0.62).toFixed(2)}
                                </span>
                            </div>
                        </div>

                        <div className="flex space-x-3">
                            <LemonButton
                                size="large"
                                type="secondary"
                                onClick={() => setShowConfirmation(false)}
                                className="flex-1"
                            >
                                Back
                            </LemonButton>
                            <LemonButton size="large" type="primary" onClick={handlePlaceBet} className="flex-1">
                                Confirm
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
        </LemonCard>
    )
}

export function BetDetailContent(): JSX.Element {
    const { betId } = useValues(hedgedHogLogic)
    const { betDefinitions, betDefinitionsLoading } = useValues(hedgedHogBetDefinitionsLogic)
    const { estimateBetPayout } = useActions(hedgedHogBetDefinitionsLogic)
    const { allBets, userBets, allBetsLoading, userBetsLoading } = useValues(hedgedHogLogic)
    const { loadAllBets, loadUserBets, goBackToBets } = useActions(hedgedHogLogic)

    const [amount, setAmount] = useState<number>(20)
    const [timeRange, setTimeRange] = useState<string>('ALL')
    const [showConfirmation, setShowConfirmation] = useState<boolean>(false)
    const [betType, setBetType] = useState<string>('')
    const [activeTab, setActiveTab] = useState<string>('all')

    const bet = betDefinitions.find((b) => b.id === betId)

    if (betDefinitionsLoading) {
        return <div>Loading...</div>
    }

    if (!bet) {
        return (
            <div className="text-center">
                <h2>Bet not found</h2>
                <LemonButton type="primary" onClick={goBackToBets}>
                    Back to bets
                </LemonButton>
            </div>
        )
    }

    const handlePlaceBet = (): void => {
        estimateBetPayout(amount, betType === 'Yes' ? 1 : 0)
        setShowConfirmation(false)
    }

    const handleTabChange = (tab: string): void => {
        setActiveTab(tab)
        if (tab === 'all' && betId) {
            loadAllBets(betId)
        } else if (tab === 'user' && betId) {
            loadUserBets(betId)
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-xl">{bet.title}</h2>
                <LemonButton type="primary" onClick={goBackToBets}>
                    Back to bets
                </LemonButton>
            </div>

            <LemonCard className="mb-4" hoverEffect={false}>
                <div className="space-y-4">
                    <div>
                        <h3 className="text-lg font-semibold mb-2">Description</h3>
                        <p>{bet.description}</p>
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="text-lg font-semibold mb-2">Bet Details</h3>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <div className="text-sm text-muted">Type</div>
                                <div>{bet.type}</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted">Closing Date</div>
                                <div>{new Date(bet.closing_date).toLocaleDateString()}</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted">Status</div>
                                <div>{bet.status}</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted">Parameters</div>
                                <div className="font-mono text-sm">{JSON.stringify(bet.bet_parameters, null, 2)}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </LemonCard>

            <div className="grid grid-cols-5 gap-4">
                <div className="col-span-1">
                    <LemonCard>
                        <div className="p-4 space-y-4">
                            <div>
                                <div className="text-sm text-muted mb-1">Volume</div>
                                <div className="font-semibold">$5,343,183</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted mb-1">Deadline</div>
                                <div className="font-semibold">May 21, 2025</div>
                            </div>
                            <div>
                                <div className="text-sm text-muted mb-1">Current probability</div>
                                <div>
                                    <span className="text-2xl font-bold">39%</span>
                                    <span className="text-sm text-success ml-2">↑ 20%</span>
                                </div>
                            </div>
                            <div>
                                <div className="text-sm text-muted mb-1">Time Remaining</div>
                                <div>
                                    <span className="text-2xl font-bold">12 hours</span>
                                </div>
                            </div>
                        </div>
                    </LemonCard>
                </div>
                <div className="col-span-3">
                    <LemonCard>
                        <div className="p-4">
                            <div className="h-96">
                                <BillingLineGraph
                                    containerClassName="h-full"
                                    series={[
                                        {
                                            id: 1,
                                            label: 'Yes',
                                            data: [85, 75, 80, 70, 60, 70, 55, 45, 35, 40],
                                            dates: [
                                                'Jan 8',
                                                'Jan 19',
                                                'Jan 31',
                                                'Feb 11',
                                                'Feb 28',
                                                'Mar 11',
                                                'Mar 31',
                                                'Apr 11',
                                                'Apr 30',
                                                'May 11',
                                            ],
                                        },
                                        {
                                            id: 2,
                                            label: 'No',
                                            data: [15, 25, 20, 35, 40, 30, 45, 55, 65, 60],
                                            dates: [
                                                'Jan 8',
                                                'Jan 19',
                                                'Jan 31',
                                                'Feb 11',
                                                'Feb 28',
                                                'Mar 11',
                                                'Mar 31',
                                                'Apr 11',
                                                'Apr 30',
                                                'May 11',
                                            ],
                                        },
                                    ]}
                                    dates={[
                                        'Jan 8',
                                        'Jan 19',
                                        'Jan 31',
                                        'Feb 11',
                                        'Feb 28',
                                        'Mar 11',
                                        'Mar 31',
                                        'Apr 11',
                                        'Apr 30',
                                        'May 11',
                                    ]}
                                    hiddenSeries={[]}
                                    valueFormatter={(value) => `${value}%`}
                                    interval="day"
                                    max={100}
                                />
                            </div>
                            <div className="w-full flex justify-between mt-4">
                                {['1H', '6H', '1D', '1W', '1M', 'ALL'].map((range) => (
                                    <LemonButton
                                        key={range}
                                        active={timeRange === range}
                                        onClick={() => setTimeRange(range)}
                                        size="small"
                                    >
                                        {range}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                    </LemonCard>
                </div>
                <div className="col-span-1">
                    <BetFlow
                        amount={amount}
                        setAmount={setAmount}
                        betType={betType}
                        setBetType={setBetType}
                        showConfirmation={showConfirmation}
                        setShowConfirmation={setShowConfirmation}
                        handlePlaceBet={handlePlaceBet}
                    />
                </div>
            </div>

            <LemonTabs
                activeKey={activeTab}
                onChange={handleTabChange}
                tabs={[
                    {
                        key: 'all',
                        label: 'All Bets',
                        content: (
                            <LemonTable
                                dataSource={allBets || []}
                                columns={[
                                    {
                                        title: 'Date',
                                        dataIndex: 'created_at',
                                        key: 'created_at',
                                        render: function RenderDate(_, record) {
                                            return new Date(record.created_at).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Bet Type',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(_, record) {
                                            const value = record.predicted_value
                                            // @ts-expect-error
                                            const prediction = typeof value === 'object' ? value.value : value
                                            return (
                                                <span className={prediction === 1 ? 'text-success' : 'text-danger'}>
                                                    {prediction === 1 ? 'Yes' : 'No'}
                                                </span>
                                            )
                                        },
                                    },
                                    {
                                        title: 'Amount',
                                        dataIndex: 'amount',
                                        key: 'amount',
                                        render: function RenderAmount(_, record) {
                                            const amount = record.amount
                                            return `$${amount.toFixed(2)}`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(_, record) {
                                            const payout = record.potential_payout
                                            return `$${payout.toFixed(2)}`
                                        },
                                    },
                                ]}
                                rowKey="id"
                                embedded
                                nouns={['bet', 'bets']}
                                emptyState="No bets placed yet"
                                loading={allBetsLoading}
                            />
                        ),
                    },
                    {
                        key: 'user',
                        label: 'My Bets',
                        content: (
                            <LemonTable
                                dataSource={userBets || []}
                                columns={[
                                    {
                                        title: 'Date',
                                        dataIndex: 'created_at',
                                        key: 'created_at',
                                        render: function RenderDate(_, record) {
                                            return new Date(record.created_at).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Bet Type',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(_, record) {
                                            const value = record.predicted_value
                                            // @ts-expect-error
                                            const prediction = typeof value === 'object' ? value.value : value
                                            return (
                                                <span className={prediction === 1 ? 'text-success' : 'text-danger'}>
                                                    {prediction === 1 ? 'Yes' : 'No'}
                                                </span>
                                            )
                                        },
                                    },
                                    {
                                        title: 'Amount',
                                        dataIndex: 'amount',
                                        key: 'amount',
                                        render: function RenderAmount(_, record) {
                                            const amount = record.amount
                                            return `$${amount.toFixed(2)}`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(_, record) {
                                            const payout = record.potential_payout
                                            return `$${payout.toFixed(2)}`
                                        },
                                    },
                                ]}
                                rowKey="id"
                                embedded
                                nouns={['bet', 'bets']}
                                emptyState="No bets placed yet"
                                loading={userBetsLoading}
                            />
                        ),
                    },
                ]}
            />
        </div>
    )
}
