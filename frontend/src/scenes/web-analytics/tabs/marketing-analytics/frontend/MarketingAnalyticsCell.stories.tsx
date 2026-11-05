import type { Meta, StoryObj } from '@storybook/react'

import { fn } from 'storybook/test'

import { MarketingAnalyticsCell } from './shared'

const meta: Meta<typeof MarketingAnalyticsCell> = {
    title: 'Scenes-App/Marketing Analytics/Metric cells',
    component: MarketingAnalyticsCell,
    args: { onClick: fn() },
}
export default meta

type Story = StoryObj<typeof MarketingAnalyticsCell>

export const ClickableAndStatic: Story = {
    render: ({ onClick }) => (
        <div className="w-96 max-w-full text-sm border rounded overflow-hidden">
            <div className="grid grid-cols-2 bg-surface-secondary border-b font-semibold">
                <div className="p-2">Clickable conversions</div>
                <div className="p-2">Static metric</div>
            </div>
            {[
                { value: 2400, previous: 2000, changeFromPreviousPct: 20, hasComparison: true },
                { value: 60, previous: 100, changeFromPreviousPct: -40, hasComparison: true },
                { value: 100, previous: 100, changeFromPreviousPct: 0, hasComparison: true },
                { value: 40, previous: null, changeFromPreviousPct: null, hasComparison: false },
                { value: 0, previous: 20, changeFromPreviousPct: -100, hasComparison: true },
                { value: null, previous: null, changeFromPreviousPct: null, hasComparison: false },
            ].map((comparison, index) => {
                const value = {
                    key: 'Conversions',
                    kind: 'unit' as const,
                    isIncreaseBad: false,
                    ...comparison,
                }
                return (
                    <div key={index} className="grid grid-cols-2 border-b last:border-b-0">
                        <MarketingAnalyticsCell
                            value={value}
                            onClick={comparison.value && comparison.value > 0 ? onClick : undefined}
                        />
                        <MarketingAnalyticsCell value={value} />
                    </div>
                )
            })}
        </div>
    ),
}
