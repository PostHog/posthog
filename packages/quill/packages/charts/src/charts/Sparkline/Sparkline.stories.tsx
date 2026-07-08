import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { Sparkline } from './Sparkline'

const RISING = [4200, 5100, 4700, 5400, 6000, 5800, 6400, 6900, 7200, 7700, 8100, 8800]
const FALLING = [9800, 9200, 8600, 8400, 7700, 7300, 6900, 6500, 6000, 5400, 4800, 4200]
const VOLATILE = [40, 65, 30, 85, 20, 70, 45, 90, 35, 75, 25, 60]
const FLAT = [50, 52, 49, 51, 50, 53, 48, 50, 51, 49, 52, 50]

const meta: Meta = { title: 'Components/HogCharts/Sparkline', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj

export const Default: Story = {
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
                <Sparkline data={FALLING} theme={theme} color="#fb7185" />
            </Stage>
        )
    },
}

export const Volatile: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={VOLATILE} theme={theme} color="#a78bfa" />
            </Stage>
        )
    },
}

export const Flat: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={120}>
                <Sparkline data={FLAT} theme={theme} />
            </Stage>
        )
    },
}

export const FillOpacityVariants: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <div className="flex flex-col gap-4 w-[360px]">
                <Sparkline data={RISING} theme={theme} fillOpacity={0.1} />
                <Sparkline data={RISING} theme={theme} fillOpacity={0.35} />
                <Sparkline data={RISING} theme={theme} fillOpacity={0.7} />
            </div>
        )
    },
}
