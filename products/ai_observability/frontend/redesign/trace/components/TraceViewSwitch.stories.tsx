import type { Meta, StoryObj } from '@storybook/react'

import { TraceViewSwitch } from './TraceViewSwitch'

const meta: Meta<typeof TraceViewSwitch> = {
    title: 'Scenes-App/AI observability/Trace view/Trace view switch',
    component: TraceViewSwitch,
    args: { onSwitch: () => {} },
}
export default meta

type Story = StoryObj<typeof TraceViewSwitch>

export const OnNewView: Story = { args: { view: 'new' } }

export const OnOldView: Story = { args: { view: 'legacy' } }
