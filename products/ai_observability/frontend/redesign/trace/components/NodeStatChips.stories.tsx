import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_STATS, withWidth } from '../storyFixtures'
import { NodeStatChips } from './NodeStatChips'

const meta: Meta<typeof NodeStatChips> = {
    title: 'Scenes-App/AI observability/Trace view/Node stat chips',
    component: NodeStatChips,
}
export default meta

type Story = StoryObj<typeof NodeStatChips>

export const Default: Story = { args: { stats: FIXTURE_STATS } }
export const Narrow: Story = { args: { stats: FIXTURE_STATS }, decorators: [withWidth(160)] }
