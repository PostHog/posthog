import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { ProportionBar } from './ProportionBar'

const CHECKOUT_OUTCOMES: Series[] = [
    { key: 'paid', label: 'Paid', data: [1180] },
    { key: 'retried', label: 'Paid after retry', data: [96] },
    { key: 'abandoned', label: 'Abandoned at payment', data: [430] },
    { key: 'declined', label: 'Card declined', data: [212] },
    { key: 'error', label: 'Payment provider error', data: [57] },
]

const TWO_PARTS: Series[] = [
    { key: 'new', label: 'New users', data: [3120] },
    { key: 'returning', label: 'Returning users', data: [5480] },
]

const meta: Meta = { title: 'Components/HogCharts/ProportionBar', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640} height={120}>
                <ProportionBar series={CHECKOUT_OUTCOMES} theme={theme} />
            </Stage>
        )
    },
}

export const TwoParts: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640} height={80}>
                <ProportionBar series={TWO_PARTS} theme={theme} />
            </Stage>
        )
    },
}

export const Narrow: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={160}>
                <ProportionBar series={CHECKOUT_OUTCOMES} theme={theme} />
            </Stage>
        )
    },
}

export const ThinWithCurrency: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640} height={80}>
                <ProportionBar
                    series={TWO_PARTS}
                    theme={theme}
                    config={{ barHeight: 8, barCornerRadius: 4 }}
                    valueFormatter={(value) => `$${value.toLocaleString()}`}
                />
            </Stage>
        )
    },
}
