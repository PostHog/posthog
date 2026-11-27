import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { ChangeTag } from './ChangeTag'

const meta: Meta<typeof ChangeTag> = {
    title: 'Scenes-App/AI observability/Diagnostics/Change tag',
    component: ChangeTag,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { label: '+40%', tone: 'bad' },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof ChangeTag>

export const Bad: Story = {}

export const Good: Story = { args: { label: '-35%', tone: 'good' } }

export const Neutral: Story = { args: { label: 'was 0', tone: 'neutral' } }
