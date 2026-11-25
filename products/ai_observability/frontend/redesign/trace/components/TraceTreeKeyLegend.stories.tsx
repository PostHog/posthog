import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { TraceTreeKeyLegend } from './TraceTreeKeyLegend'

const meta: Meta<typeof TraceTreeKeyLegend> = {
    title: 'Scenes-App/AI observability/Trace view/Trace tree key legend',
    component: TraceTreeKeyLegend,
    decorators: [withWidth(288)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof TraceTreeKeyLegend>

export const StepsAndTraces: Story = { args: { showTraceKeys: true } }
export const StepsOnly: Story = { args: { showTraceKeys: false } }
