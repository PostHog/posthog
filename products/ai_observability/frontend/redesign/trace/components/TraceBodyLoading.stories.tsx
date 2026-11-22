import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TraceBodyLoading } from './TraceBodyLoading'

const meta: Meta<typeof TraceBodyLoading> = {
    title: 'Scenes-App/AI observability/Trace view/Trace body loading',
    component: TraceBodyLoading,
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}
export default meta

type Story = StoryObj<typeof TraceBodyLoading>

export const Default: Story = { decorators: [withWidth(1100)] }
export const Narrow: Story = { decorators: [withWidth(420)] }
