import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TurnTiming } from './TurnTiming'

const wide = [withWidth(240)]

const meta: Meta<typeof TurnTiming> = {
    title: 'Scenes-App/AI observability/Trace view/Turn timing',
    component: TurnTiming,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { timestamp: '2026-09-01T10:03:00Z', waitMs: 2_400, waitSlow: false },
}
export default meta

type Story = StoryObj<typeof TurnTiming>

export const Normal: Story = { decorators: wide }
export const SlowWait: Story = { args: { waitMs: 18_000, waitSlow: true }, decorators: wide }
export const WaitUnknown: Story = { args: { waitMs: null }, decorators: wide }
export const Narrow: Story = { args: { waitMs: 18_000, waitSlow: true }, decorators: [withWidth(80)] }
