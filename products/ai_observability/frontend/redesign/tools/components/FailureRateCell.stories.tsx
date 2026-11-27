import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { FailureRateCell } from './FailureRateCell'

const meta: Meta<typeof FailureRateCell> = {
    title: 'Scenes-App/AI observability/Tools/Failure rate cell',
    component: FailureRateCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tool: { failureRate: 0.012, failureState: 'captured', isFailing: false } },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof FailureRateCell>

export const Captured: Story = {}

export const Failing: Story = { args: { tool: { failureRate: 0.083, failureState: 'captured', isFailing: true } } }

export const NotCaptured: Story = {
    args: { tool: { failureRate: null, failureState: 'not_captured', isFailing: false } },
}
