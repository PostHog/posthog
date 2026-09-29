import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_STATS } from '../storyFixtures'
import { NodeStatsLine } from './NodeStatsLine'

const meta: Meta<typeof NodeStatsLine> = {
    title: 'Scenes-App/AI observability/Trace view/Node stats line',
    component: NodeStatsLine,
}
export default meta

type Story = StoryObj<typeof NodeStatsLine>

export const Full: Story = { args: { stats: FIXTURE_STATS, model: 'gpt-4.1-mini' } }
export const Compact: Story = { args: { stats: FIXTURE_STATS, model: 'gpt-4.1-mini', compact: true } }
export const LatencyOnly: Story = {
    args: { stats: { costUsd: null, inputTokens: null, outputTokens: null, cacheReadTokens: null, latencyMs: 260 } },
}
