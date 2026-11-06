import type { Meta, StoryObj } from '@storybook/react'

import { SampleDataTag } from './SampleDataTag'

const meta: Meta<typeof SampleDataTag> = {
    component: SampleDataTag,
    title: 'Components/Sample Data Tag',
}
export default meta

type Story = StoryObj<typeof SampleDataTag>

export const Default: Story = {}
