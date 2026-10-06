import type { Meta, StoryObj } from '@storybook/react'

import { MarketingAnalyticsCell } from './shared'

const meta: Meta<typeof MarketingAnalyticsCell> = {
    title: 'Scenes-App/Marketing Analytics/Metric cells',
    component: MarketingAnalyticsCell,
}
export default meta

type Story = StoryObj<typeof MarketingAnalyticsCell>

export const ClickableAndStatic: Story = {
    render: () => (
        <div className="w-96 grid grid-cols-2 text-sm">
            {[
                { value: 2400, previous: 2000, changeFromPreviousPct: 20 },
                { value: 60, previous: 100, changeFromPreviousPct: -40 },
                { value: 100, previous: 100, changeFromPreviousPct: 0 },
            ].map((comparison) => {
                const value = {
                    key: 'Conversions',
                    kind: 'unit' as const,
                    hasComparison: true,
                    isIncreaseBad: false,
                    ...comparison,
                }
                return (
                    <div key={comparison.value} className="col-span-2 grid grid-cols-2 border-b">
                        <MarketingAnalyticsCell value={value} onClick={() => alert('View people')} />
                        <MarketingAnalyticsCell value={value} />
                    </div>
                )
            })}
        </div>
    ),
}
