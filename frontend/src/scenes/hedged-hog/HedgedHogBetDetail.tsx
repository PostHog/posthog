import { IconX } from '@posthog/icons'
import { Separator } from '@radix-ui/react-dropdown-menu'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import hogecoin from 'public/hedgehog/hodgecoin.png'
import { useEffect, useState } from 'react'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'

import { hedgedHogBetDefinitionsLogic } from './hedgedHogBetDefinitionsLogic'
import { hedgedHogLogic } from './hedgedHogLogic'

interface BetFlowProps {
    amount: number
    setAmount: (amount: number) => void
    selectedBucket: { min: number; max: number; probability: number } | null
    setSelectedBucket: (bucket: { min: number; max: number; probability: number } | null) => void
    showConfirmation: boolean
    setShowConfirmation: (show: boolean) => void
    handlePlaceBet: () => void
    bucketRanges: Array<{ min: number; max: number; probability: number }>
}

const BetFlow = ({
    amount,
    setAmount,
    selectedBucket,
    setSelectedBucket,
    showConfirmation,
    setShowConfirmation,
    handlePlaceBet,
    bucketRanges,
}: BetFlowProps): JSX.Element => {
    const getOdds = (probability: number): number => (probability > 0 ? 1 / probability : 0)
    const getPotentialPayout = (amount: number, probability: number): string =>
        `$${(amount * getOdds(probability)).toFixed(2)}`

    return (
        <LemonCard className="h-full" hoverEffect={false}>
            <div>
                {!showConfirmation ? (
                    <div className="space-y-6">
                        <div>
                            <h3 className="font-semibold mb-4">Place a bet</h3>
                            <div className="space-y-1">
                                {bucketRanges.map((bucket, index) => (
                                    <div key={index} className="flex items-center gap-2 py-2 border-b last:border-b-0">
                                        <div className="flex-grow">
                                            <div className="font-medium">
                                                {index === 0
                                                    ? `≤${Math.round(bucket.max)}`
                                                    : index === bucketRanges.length - 1
                                                    ? `≥${Math.round(bucket.min)}`
                                                    : `${Math.round(bucket.min)}-${Math.round(bucket.max)}`}
                                            </div>
                                            <div className="text-sm text-muted">
                                                {Math.round(bucket.probability * 100)}% probability
                                            </div>
                                        </div>
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={() => {
                                                setSelectedBucket(bucket)
                                                setShowConfirmation(true)
                                            }}
                                            disabledReason={amount === 0 && 'The amount must be greater than 0'}
                                        >
                                            Bet
                                        </LemonButton>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div>
                            <h3 className="font-semibold mb-2">Amount</h3>

                            <LemonInput
                                className="text-2xl font-bold"
                                type="text"
                                prefix={
                                    <div>
                                        <img src={hogecoin} alt="Hogecoin" className="h-8 w-auto" />
                                    </div>
                                }
                                value={amount.toString()}
                                onChange={(value) => setAmount(Number(value) || 0)}
                            />

                            <Separator className="my-2" />

                            <div className="flex flex-col gap-2">
                                {['+1', '+20', '+100'].map((amt) => (
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        center
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
                    </div>
                ) : (
                    <div className="bg-bg-light">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="font-semibold text-lg mb-0">Confirm your bet</h3>
                            <LemonButton size="small" type="secondary" onClick={() => setShowConfirmation(false)}>
                                <IconX />
                            </LemonButton>
                        </div>
                        <div className="space-y-4 mb-8">
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Range:</span>
                                <span className="text-lg font-semibold">
                                    {selectedBucket
                                        ? `${Math.round(selectedBucket.min)}-${Math.round(
                                              selectedBucket.max
                                          )} (${Math.round(selectedBucket.probability * 100)}%)`
                                        : ''}
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Amount:</span>
                                <span className="text-lg font-semibold">{amount.toFixed(2)}</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted">Odds:</span>
                                <span className="text-lg font-semibold">
                                    {selectedBucket ? `${getOdds(selectedBucket.probability).toFixed(2)}x` : '--'}
                                </span>
                            </div>
                            <LemonDivider className="my-4" />
                            <div className="flex justify-between items-center">
                                <span className="font-semibold">Potential Payout:</span>
                                <span className="text-success text-lg font-bold">
                                    {selectedBucket ? getPotentialPayout(amount, selectedBucket.probability) : '$0.00'}
                                </span>
                            </div>
                        </div>

                        <LemonButton type="primary" fullWidth center onClick={handlePlaceBet}>
                            Confirm
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonCard>
    )
}

export function BetDetailContent(): JSX.Element {
    const { betId } = useValues(hedgedHogLogic)
    const { betDefinitions, betDefinitionsLoading } = useValues(hedgedHogBetDefinitionsLogic)
    const { allBets, allBetsLoading } = useValues(hedgedHogLogic)
    const { loadAllBets, loadUserBets, goBackToBets, placeBet } = useActions(hedgedHogLogic)
    const { userBets, userBetsLoading } = useValues(hedgedHogLogic)

    const [amount, setAmount] = useState<number>(20)
    const [timeRange, setTimeRange] = useState<string>('ALL')
    const [showConfirmation, setShowConfirmation] = useState<boolean>(false)
    const [selectedBucket, setSelectedBucket] = useState<{ min: number; max: number; probability: number } | null>(null)
    const [activeTab, setActiveTab] = useState<string>('all')

    useEffect(() => {
        if (betId) {
            loadAllBets(betId)
        }
    }, [betId, loadAllBets])

    const tradingVolume = allBets.reduce((sum: number, b: any) => sum + Number(b.amount), 0)

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

    const latestDistribution = bet.latest_distribution

    const handlePlaceBet = (): void => {
        if (betId && selectedBucket) {
            placeBet(betId, amount, { min: selectedBucket.min, max: selectedBucket.max })
        }
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

    // Transform probability distributions for the chart
    const chartData = bet.probability_distributions.map((dist) => ({
        date: new Date(dist.created_at).toLocaleDateString(),
        ranges: dist.buckets.map((bucket, index) => ({
            range:
                index === 0
                    ? `≤${Math.round(bucket.max)}`
                    : index === dist.buckets.length - 1
                    ? `≥${Math.round(bucket.min)}`
                    : `${Math.round(bucket.min)}-${Math.round(bucket.max)}`,
            probability: bucket.probability * 100,
        })),
    }))

    // Get unique range labels for the series
    const rangeLabels =
        latestDistribution?.buckets.map((bucket, index) =>
            index === 0
                ? `≤${Math.round(bucket.max)}`
                : index === latestDistribution.buckets.length - 1
                ? `≥${Math.round(bucket.min)}`
                : `${Math.round(bucket.min)}-${Math.round(bucket.max)}`
        ) || []

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl mb-1">{bet.title}</h2>
                    <div className="mb-4">
                        <p className="text-xs text-muted">{bet.description}</p>
                    </div>
                </div>
                <LemonButton type="primary" onClick={goBackToBets}>
                    Back to bets
                </LemonButton>
            </div>

            <div className="flex gap-4 mb-4">
                <div className="space-y-1 border-r pr-4">
                    <div className="text-sm text-muted">Type</div>
                    <div>{bet.type}</div>
                </div>
                <div className="space-y-1">
                    <div className="text-sm text-muted">Status</div>
                    <div className={`${bet.status === 'active' ? 'text-success' : 'text-danger'}`}>{bet.status}</div>
                </div>
            </div>

            <div className="grid grid-cols-4 gap-4">
                <div className="col-span-3">
                    <div className="border rounded bg-surface-primary relative border-primary">
                        <div className="flex">
                            <div className="w-1/4 p-6 bg-bg-light space-y-4 bg-surface-secondary rounded-l-md">
                                <div>
                                    <div className="text-sm text-muted mb-1">Trading Volume</div>
                                    <div className="font-semibold">{tradingVolume.toLocaleString()}</div>
                                </div>
                                <div>
                                    <div className="text-sm text-muted mb-1">Closing date</div>
                                    <div className="font-semibold">
                                        {new Date(bet.closing_date).toLocaleDateString()}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-sm text-muted mb-1">Time remaining</div>
                                    <div>
                                        <span className="font-semibold">
                                            {Math.ceil(
                                                (new Date(bet.closing_date).getTime() - Date.now()) / (1000 * 60 * 60)
                                            )}{' '}
                                            hours
                                        </span>
                                    </div>
                                </div>
                            </div>
                            <div className="p-6 w-3/4">
                                <div className="h-132">
                                    <BillingLineGraph
                                        containerClassName="h-full"
                                        series={rangeLabels.map((range, index) => ({
                                            id: index + 1,
                                            label: range,
                                            data: chartData.map((d) => d.ranges[index].probability),
                                            dates: chartData.map((d) => d.date),
                                        }))}
                                        dates={chartData.map((d) => d.date)}
                                        hiddenSeries={[]}
                                        valueFormatter={(value) => `${value}%`}
                                        interval="day"
                                        max={100}
                                        showLegend={false}
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
                        </div>
                    </div>
                </div>
                <div className="col-span-1">
                    <BetFlow
                        amount={amount}
                        setAmount={setAmount}
                        selectedBucket={selectedBucket}
                        setSelectedBucket={setSelectedBucket}
                        showConfirmation={showConfirmation}
                        setShowConfirmation={setShowConfirmation}
                        handlePlaceBet={handlePlaceBet}
                        bucketRanges={latestDistribution?.buckets || []}
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
                                        title: 'Timestamp',
                                        dataIndex: 'created_at',
                                        key: 'created_at',
                                        render: function RenderDate(_, record) {
                                            return new Date(record.created_at).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Prediction',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(_, record) {
                                            const range = record.predicted_value
                                            return range &&
                                                typeof range === 'object' &&
                                                'min' in range &&
                                                'max' in range
                                                ? `${Math.round(range.min)}-${Math.round(range.max)}`
                                                : ''
                                        },
                                    },
                                    {
                                        title: 'Amount',
                                        dataIndex: 'amount',
                                        key: 'amount',
                                        render: function RenderAmount(_, record) {
                                            const amount = record.amount
                                            const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount
                                            return `${numAmount.toFixed(2)} Hogecoins`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(_, record) {
                                            const payout = record.potential_payout
                                            const numPayout = typeof payout === 'string' ? parseFloat(payout) : payout
                                            return `${numPayout.toFixed(2)} Hogecoins`
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
                                        title: 'Timestamp',
                                        dataIndex: 'created_at',
                                        key: 'created_at',
                                        render: function RenderDate(_, record) {
                                            return new Date(record.created_at).toLocaleDateString()
                                        },
                                    },
                                    {
                                        title: 'Prediction',
                                        dataIndex: 'predicted_value',
                                        key: 'predicted_value',
                                        render: function RenderType(_, record) {
                                            const range = record.predicted_value
                                            return range &&
                                                typeof range === 'object' &&
                                                'min' in range &&
                                                'max' in range
                                                ? `${Math.round(range.min)}-${Math.round(range.max)}`
                                                : ''
                                        },
                                    },
                                    {
                                        title: 'Amount',
                                        dataIndex: 'amount',
                                        key: 'amount',
                                        render: function RenderAmount(_, record) {
                                            const amount = record.amount
                                            const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount
                                            return `${numAmount.toFixed(2)} Hogecoins`
                                        },
                                    },
                                    {
                                        title: 'Potential Payout',
                                        dataIndex: 'potential_payout',
                                        key: 'potential_payout',
                                        render: function RenderPayout(_, record) {
                                            const payout = record.potential_payout
                                            const numPayout = typeof payout === 'string' ? parseFloat(payout) : payout
                                            return `${numPayout.toFixed(2)} Hogecoins`
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
