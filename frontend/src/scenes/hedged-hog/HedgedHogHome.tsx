import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'

export function HomeContent(): JSX.Element {
    const [amount, setAmount] = useState<number>(20)
    const [timeRange, setTimeRange] = useState<string>('ALL')
    const [activeTab, setActiveTab] = useState<string>('your-bets')

    const mockData = {
        dates: ['Jan 8', 'Jan 19', 'Jan 31', 'Feb 11', 'Feb 28', 'Mar 11', 'Mar 31', 'Apr 11', 'Apr 30', 'May 11'],
        values: [85, 75, 80, 70, 60, 70, 55, 45, 35, 40],
    }
    const secondLineData = [15, 25, 20, 35, 40, 30, 45, 55, 65, 60]

    return (
        <div className="hedged-hog-scene">
            <PageHeader />

            <div className="border rounded-lg p-4">
                <div className="mb-4">
                    <h2 className="text-xl font-semibold">Analytics events by May 21st</h2>
                </div>

                <div className="grid grid-cols-5 gap-4">
                    {/* Left info column - 1/5 of the grid */}
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
                                <span className="text-2xl font-bold text-blue-500">39%</span>
                                <span className="text-sm text-success ml-2">↑ 20%</span>
                            </div>
                        </div>
                        <div className="mb-4">
                            <div className="text-sm text-muted mb-1">Time Remaining</div>
                            <div>
                                <span className="text-2xl font-bold text-blue-500">12 hours </span>
                            </div>
                        </div>
                    </div>

                    {/* Middle chart column - 3/5 of the grid */}
                    <div className="col-span-3 rounded-md relative">
                        <div className="h-full w-full p-2">
                            <div>
                                <BillingLineGraph
                                    containerClassName="h-80"
                                    series={[
                                        {
                                            id: 1,
                                            label: 'Yes',
                                            data: mockData.values,
                                            dates: mockData.dates,
                                        },
                                        {
                                            id: 2,
                                            label: 'No',
                                            data: secondLineData,
                                            dates: mockData.dates,
                                        },
                                    ]}
                                    dates={mockData.dates}
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
                        <div />
                    </div>

                    <div className="col-span-1 pl-2">
                        <div className="mt-4 space-y-4">
                            <div className="space-y-2">
                                <LemonButton fullWidth center type="primary">
                                    Yes 39¢
                                </LemonButton>
                                <LemonButton fullWidth center type="primary">
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

                            <div>
                                <div className="flex justify-between text-sm mb-1">
                                    <span>To win</span>
                                    <span className="text-green-500 font-bold">$87.18</span>
                                </div>
                                <div className="flex justify-between text-xs text-muted">
                                    <span>Avg. Price</span>
                                    <span>39¢</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <LemonTabs
                    activeKey={activeTab}
                    onChange={(newKey) => setActiveTab(newKey)}
                    tabs={[
                        {
                            key: 'your-bets',
                            label: 'Your Hedges',
                        },
                        {
                            key: 'all-bets',
                            label: 'All Hedges',
                        },
                    ]}
                />

                <LemonTable
                    dataSource={[
                        { id: 1, date: 'May 8, 2023 14:32', betType: 'Yes', price: 0.39, betAmount: 19.5 },
                        { id: 2, date: 'May 7, 2023 08:15', betType: 'No', price: 0.62, betAmount: 15.5 },
                        { id: 3, date: 'May 5, 2023 19:42', betType: 'Yes', price: 0.35, betAmount: 35.0 },
                        { id: 4, date: 'May 2, 2023 11:07', betType: 'Yes', price: 0.33, betAmount: 9.9 },
                    ]}
                    columns={[
                        {
                            title: 'Date',
                            dataIndex: 'date',
                            key: 'date',
                        },
                        {
                            title: 'Bet Type',
                            dataIndex: 'betType',
                            key: 'betType',
                            render: function RenderType(betType: string | number | undefined) {
                                return (
                                    <span className={betType === 'Yes' ? 'text-success' : 'text-danger'}>
                                        {betType}
                                    </span>
                                )
                            },
                        },
                        {
                            title: 'Price',
                            dataIndex: 'price',
                            key: 'price',
                            render: function RenderPrice(price: string | number | undefined) {
                                return `${(Number(price) * 100).toFixed(0)}¢`
                            },
                        },
                        {
                            title: 'Bet Amount',
                            dataIndex: 'betAmount',
                            key: 'betAmount',
                        },
                    ]}
                    rowKey="id"
                    embedded
                    nouns={['trade', 'trades']}
                    emptyState="No trades for Analytics events prediction yet"
                />
            </div>
        </div>
    )
}
