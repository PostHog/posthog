import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { Sparkline } from './Sparkline'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const RISING = [4200, 5100, 4700, 5400, 6000, 5800, 6400, 6900, 7200, 7700, 8100, 8800]
const FALLING = [9800, 9200, 8600, 8400, 7700, 7300, 6900, 6500, 6000, 5400, 4800, 4200]
const VOLATILE = [40, 65, 30, 85, 20, 70, 45, 90, 35, 75, 25, 60]
const FLAT = [50, 52, 49, 51, 50, 53, 48, 50, 51, 49, 52, 50]

const meta: Meta = { title: 'Components/HogCharts/Sparkline', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={RISING} labels={MONTHS} theme={theme} />
            </Stage>
        )
    },
}

export const WithoutLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={RISING} theme={theme} />
            </Stage>
        )
    },
}

export const CustomColor: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={FALLING} labels={MONTHS} theme={theme} color="#fb7185" />
            </Stage>
        )
    },
}

export const Volatile: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={VOLATILE} labels={MONTHS} theme={theme} color="#a78bfa" />
            </Stage>
        )
    },
}

export const Flat: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={FLAT} labels={MONTHS} theme={theme} />
            </Stage>
        )
    },
}

/** Three heights side-by-side — the inline `40` size is what's typically embedded in a table row. */
export const HeightVariants: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24, width: 360 }}>
                <Sparkline data={RISING} labels={MONTHS} theme={theme} height={40} />
                <Sparkline data={RISING} labels={MONTHS} theme={theme} height={120} />
                <Sparkline data={RISING} labels={MONTHS} theme={theme} height={200} />
            </div>
        )
    },
}

/** Lower `fillOpacity` makes the gradient fade earlier; higher values keep more area visible. */
export const FillOpacityVariants: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: 360 }}>
                <Sparkline data={RISING} labels={MONTHS} theme={theme} fillOpacity={0.1} />
                <Sparkline data={RISING} labels={MONTHS} theme={theme} fillOpacity={0.35} />
                <Sparkline data={RISING} labels={MONTHS} theme={theme} fillOpacity={0.7} />
            </div>
        )
    },
}

export const SinglePoint: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={[42]} labels={['Today']} theme={theme} />
            </Stage>
        )
    },
}

export const Empty: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={[]} theme={theme} />
            </Stage>
        )
    },
}

/** Demonstrates `onHoverIndexChange` — the hovered index lifts out of the chart so callers
 *  can drive a sibling element (e.g. a headline number). */
export const HoverIndexCallback: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const [hoverIndex, setHoverIndex] = useState(-1)
        const activeLabel = hoverIndex >= 0 ? MONTHS[hoverIndex] : 'Hover the chart'
        const activeValue = hoverIndex >= 0 ? RISING[hoverIndex] : RISING[RISING.length - 1]
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ width: 360, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="text-xs text-secondary">{activeLabel}</div>
                <div className="text-2xl font-semibold">US${activeValue.toLocaleString()}</div>
                <Sparkline
                    data={RISING}
                    labels={MONTHS}
                    theme={theme}
                    color="#22d3ee"
                    height={100}
                    onHoverIndexChange={setHoverIndex}
                />
            </div>
        )
    },
}
