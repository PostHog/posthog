import { Meta, StoryObj } from '@storybook/react'

import { Stage } from '../../story-helpers'
import { ChartLoadingOverlay, HogLoader } from './ChartLoadingOverlay'

const meta: Meta = { title: 'Components/HogCharts/ChartLoadingOverlay', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Loader: Story = {
    render: () => (
        <Stage width={200} height={120}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                <HogLoader size={80} />
            </div>
        </Stage>
    ),
}

export const SmallLoader: Story = {
    render: () => (
        <Stage width={200} height={120}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                <HogLoader size={40} />
            </div>
        </Stage>
    ),
}

export const OverlaidOnChart: Story = {
    render: () => (
        <Stage width={480} height={240}>
            <div style={{ position: 'relative', width: '100%', height: '100%', background: 'var(--bg-surface-primary, #fff)', borderRadius: 8 }}>
                {/* Simulate a chart skeleton */}
                <svg width="100%" height="100%" style={{ opacity: 0.08 }}>
                    <line x1="48" y1="16" x2="48" y2="200" stroke="currentColor" strokeWidth="1" />
                    <line x1="48" y1="200" x2="464" y2="200" stroke="currentColor" strokeWidth="1" />
                    {[0.2, 0.45, 0.7, 0.9].map((v, i) => (
                        <line key={i} x1="48" y1={200 - v * 184} x2="464" y2={200 - v * 184} stroke="currentColor" strokeWidth="1" strokeDasharray="4 4" />
                    ))}
                </svg>
                <ChartLoadingOverlay size={64} />
            </div>
        </Stage>
    ),
}
