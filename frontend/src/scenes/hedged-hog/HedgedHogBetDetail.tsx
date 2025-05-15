import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'
import { urls } from 'scenes/urls'

import { hedgedHogBetDefinitionsLogic } from './hedgedHogBetDefinitionsLogic'
import { hedgedHogLogic } from './hedgedHogLogic'

export function BetDetailContent(): JSX.Element {
    const { betId } = useValues(hedgedHogLogic)
    const { betDefinitions, betDefinitionsLoading } = useValues(hedgedHogBetDefinitionsLogic)
    const { estimateBetPayout } = useActions(hedgedHogBetDefinitionsLogic)
    const { push } = useActions(router)
    const { allBets, userBets, allBetsLoading, userBetsLoading } = useValues(hedgedHogLogic)
    const { loadAllBets, loadUserBets } = useActions(hedgedHogLogic)

    const [amount, setAmount] = useState<number>(20)
    const [timeRange, setTimeRange] = useState<string>('ALL')
    const [showConfirmation, setShowConfirmation] = useState<boolean>(false)
    const [betType, setBetType] = useState<string>('')
    const [activeTab, setActiveTab] = useState<string>('all')

    const bet = betDefinitions.find((b) => b.id === betId)

    if (betDefinitionsLoading) {
        return <LemonSkeleton className="h-80" />
    }

    if (!bet) {
        return (
            <div className="text-center">
                <h2>Bet not found</h2>
                <LemonButton type="primary" onClick={() => push(urls.hedgedHog())}>
                    Back to Bets
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
                <h2 className="text-xl mb-0">{bet.title}</h2>
                <LemonButton type="primary" onClick={() => push(urls.hedgedHog())}>
                    Back to Bets
                </LemonButton>
            </div>

            <div className="grid grid-cols-5 gap-4">
                <div className="col-span-1 pr-2">
                    <div className="mb-4">
                        <div className="text-sm text-muted mb-1">Volume</div>
                        <div className="font-semibold">$5,343,183</div>
                    </div>
                    <div className="mb-4">
                        <div className="text-sm text-muted mb-1">Deadline</div>
                        <div className="font-semibold">May 21, 2025</div>
                    </div>
                    <div className="mb-4">
                        <div className="text-sm text-muted mb-1">Current probability</div>
                        <div>
                            <span className="text-2xl font-bold">39%</span>
                            <span className="text-sm text-success ml-2">↑ 20%</span>
                        </div>
                    </div>
                    <div className="mb-4">
                        <div className="text-sm text-muted mb-1">Time Remaining</div>
                        <div>
                            <span className="text-2xl font-bold">12 hours</span>
                        </div>
                    </div>

                    <div className="mt-4 space-y-4">
                        {!showConfirmation ? (
                            <>
                                <div className="space-y-2">
                                    <LemonButton
                                        fullWidth
                                        center
                                        type="primary"
                                        onClick={() => {
                                            setBetType('Yes')
                                            setShowConfirmation(true)
                                        }}
                                        disabledReason={amount === 0 && 'The amount must be greater than 0'}
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
                                    >
                                        No 62¢
                                    </LemonButton>
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

                                <div className="flex justify-between">
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
                            </>
                        ) : (
                            <div className="bg-bg-light rounded p-4 border">
                                <h3 className="font-semibold text-lg mb-4">Confirm Your Bet</h3>

                                <div className="space-y-3 mb-6">
                                    <div className="flex justify-between">
                                        <span>Bet Type:</span>
                                        <span
                                            className={
                                                betType === 'Yes' ? 'text-success font-bold' : 'text-danger font-bold'
                                            }
                                        >
                                            {betType}
                                        </span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Amount:</span>
                                        <span className="font-bold">${amount.toFixed(2)}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Price:</span>
                                        <span className="font-bold">{betType === 'Yes' ? '39¢' : '62¢'}</span>
                                    </div>
                                    <div className="flex justify-between border-t pt-2 mt-2">
                                        <span className="font-semibold">Potential Payout:</span>
                                        <span className="text-green-500 font-bold">
                                            $
                                            {betType === 'Yes'
                                                ? (amount / 0.39).toFixed(2)
                                                : (amount / 0.62).toFixed(2)}
                                        </span>
                                    </div>
                                </div>

                                <div className="flex space-x-2">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => setShowConfirmation(false)}
                                    >
                                        Back
                                    </LemonButton>
                                    <LemonButton size="small" type="primary" onClick={handlePlaceBet}>
                                        Confirm
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                <div className="col-span-4">
                    <div className="h-full w-full">
                        <div>
                            <BillingLineGraph
                                containerClassName="h-80"
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
                        <div className="w-full flex justify-between">
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
                                        render: function RenderDate(date: string) {
                                            return new Date(date).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Bet Type',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(value: any) {
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
                                        render: function RenderAmount(amount: number) {
                                            return `$${amount.toFixed(2)}`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(payout: number) {
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
                                        render: function RenderDate(date: string) {
                                            return new Date(date).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Bet Type',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(value: any) {
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
                                        render: function RenderAmount(amount: number) {
                                            return `$${amount.toFixed(2)}`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(payout: number) {
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
        </div>
    )
}
