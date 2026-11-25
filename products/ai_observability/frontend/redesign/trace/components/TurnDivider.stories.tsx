import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TurnDivider } from './TurnDivider'

const wide = [withWidth(480)]

const meta: Meta<typeof TurnDivider> = {
    title: 'Scenes-App/AI observability/Trace view/Turn divider',
    component: TurnDivider,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { startedAt: null, silenceMs: 5 * 60_000 },
}
export default meta

type Story = StoryObj<typeof TurnDivider>

export const Minutes: Story = { decorators: wide }
export const Hours: Story = { args: { silenceMs: 3 * 60 * 60_000 }, decorators: wide }
export const Days: Story = { args: { silenceMs: 2 * 24 * 60 * 60_000 }, decorators: wide }
export const StartOfDay: Story = { args: { startedAt: '2026-09-01T10:15:00Z', silenceMs: null }, decorators: wide }
export const StartOfDayAfterSilence: Story = {
    args: { startedAt: '2026-09-02T09:05:00Z', silenceMs: 22 * 60 * 60_000 },
    decorators: wide,
}
export const Narrow: Story = {
    args: { startedAt: '2026-09-02T09:05:00Z', silenceMs: 22 * 60 * 60_000 },
    decorators: [withWidth(160)],
}
