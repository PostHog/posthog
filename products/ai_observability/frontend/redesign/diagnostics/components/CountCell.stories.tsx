import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { CountCell } from './CountCell'

const meta: Meta<typeof CountCell> = {
    title: 'Scenes-App/AI observability/Diagnostics/Count cell',
    component: CountCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { value: 610, share: { status: 'ready', value: 0.4237 } },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof CountCell>

export const WithShare: Story = {}

export const ShareFailed: Story = { args: { share: { status: 'error' } } }
