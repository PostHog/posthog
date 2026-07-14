import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { funnelFromCounts } from './funnel-data'
import { FunnelChart } from './FunnelChart'

const STEPS = ['Visited signup', 'Created account', 'Started trial', 'Invited teammate']

const SINGLE = funnelFromCounts([
    { label: STEPS[0], count: 12840 },
    { label: STEPS[1], count: 7921 },
    { label: STEPS[2], count: 4102 },
    { label: STEPS[3], count: 1289 },
])

// Multi-variant comparison: every variant starts at 100% (the first step is the basis).
const VARIANT_STEPS = ['Viewed pricing', 'Started checkout']
const VARIANT_SERIES: Series[] = [
    { key: 'control', label: 'control', data: [100, 22.4] },
    { key: 'test', label: 'test', data: [100, 27.9] },
]

const meta: Meta = { title: 'Components/HogCharts/FunnelChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640}>
                <FunnelChart steps={SINGLE.steps} series={SINGLE.series} theme={theme} />
            </Stage>
        )
    },
}

export const MultipleVariants: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={520}>
                <FunnelChart
                    steps={VARIANT_STEPS}
                    series={VARIANT_SERIES}
                    theme={theme}
                    onStepClick={({ stepIndex, series, converted }) =>
                        alert(`${converted ? 'Converted' : 'Dropped off'} · step ${stepIndex + 1} · ${series.label}`)
                    }
                />
            </Stage>
        )
    },
}

export const WithStepFooter: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const counts = [12840, 7921, 4102, 1289]
        return (
            <Stage width={720} height={340}>
                <FunnelChart
                    steps={SINGLE.steps}
                    series={SINGLE.series}
                    theme={theme}
                    stepFooter={(stepIndex) => (
                        <div className="text-xs leading-tight">
                            <div className="font-semibold truncate" title={SINGLE.steps[stepIndex]}>
                                {stepIndex + 1}. {SINGLE.steps[stepIndex]}
                            </div>
                            <div>{counts[stepIndex].toLocaleString()} users</div>
                            <div>{SINGLE.series[0].data[stepIndex].toFixed(1)}% of total</div>
                        </div>
                    )}
                />
            </Stage>
        )
    },
}

export const FewStepsClustered: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={640}>
                <FunnelChart
                    steps={VARIANT_STEPS}
                    series={VARIANT_SERIES}
                    theme={theme}
                    config={{ maxBandRange: 320, legend: { show: true, interactive: false } }}
                />
            </Stage>
        )
    },
}
