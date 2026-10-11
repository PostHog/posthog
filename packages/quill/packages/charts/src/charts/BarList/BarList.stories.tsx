import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { BarList } from './BarList'

const BROWSERS: Series[] = [
    { key: 'chrome', label: 'Chrome', data: [4812] },
    { key: 'safari', label: 'Safari', data: [1630] },
    { key: 'firefox', label: 'Firefox', data: [744] },
    { key: 'edge', label: 'Edge', data: [512] },
    { key: 'samsung', label: 'Samsung Internet', data: [133] },
    { key: 'opera', label: 'Opera', data: [61] },
    { key: 'other', label: 'Other browsers', data: [12] },
]

const LONG_LABELS: Series[] = [
    { key: 'pricing', label: '/pricing/compare-plans-and-features', data: [920] },
    { key: 'docs', label: '/docs/getting-started/installation-guide', data: [610] },
    { key: 'blog', label: '/blog/how-we-ship-small-changes-every-day', data: [280] },
    { key: 'home', label: '/', data: [95] },
]

const meta: Meta = { title: 'Components/HogCharts/BarList', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={480} height={200}>
                <BarList series={BROWSERS} theme={theme} config={{ valueDisplay: 'percent' }} />
            </Stage>
        )
    },
}

// The rows are the top four of a larger whole, so the track is that whole and the bars are shares of it.
export const ShareOfTotal: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={480} height={136}>
                <BarList
                    series={BROWSERS.slice(0, 4)}
                    theme={theme}
                    total={7904}
                    config={{ scale: 'total', valueDisplay: 'both', rowHeight: 32, barHeight: 16 }}
                    renderLabel={(series) => (
                        <>
                            <span
                                className="h-2 w-2 shrink-0 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props -- per-row color
                                style={{ background: series.color }}
                            />
                            <span className="truncate">{series.label}</span>
                        </>
                    )}
                />
            </Stage>
        )
    },
}

export const NarrowWithLongLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={280} height={120}>
                <BarList series={LONG_LABELS} theme={theme} />
            </Stage>
        )
    },
}

// Above the bar, a long label reads in full and the bar takes the full width of a narrow list.
export const LabelsOnTop: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={280} height={176}>
                <BarList
                    series={LONG_LABELS}
                    theme={theme}
                    config={{ labelPosition: 'top', scale: 'total', valueDisplay: 'both' }}
                />
            </Stage>
        )
    },
}
