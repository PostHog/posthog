import type { Meta, StoryObj } from '@storybook/react'

import { IconCheck } from '@posthog/icons'

import { ChipButton } from './ChipButton'

const meta: Meta<typeof ChipButton> = {
    title: 'Scenes-App/AI observability/Trace view/Chip button',
    component: ChipButton,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { children: '+2', onClick: () => {} },
}
export default meta

type Story = StoryObj<typeof ChipButton>

export const Plain: Story = {}
export const WithIconAndType: Story = { args: { children: 'Evals 3/3 passed', type: 'success', icon: <IconCheck /> } }
