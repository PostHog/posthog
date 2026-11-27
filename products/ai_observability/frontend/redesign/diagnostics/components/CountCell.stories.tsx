import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { CountCell } from './CountCell'

const meta: Meta<typeof CountCell> = {
    title: 'Scenes-App/AI observability/Diagnostics/Count cell',
    component: CountCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { value: 1240 },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof CountCell>

export const Count: Story = {}
