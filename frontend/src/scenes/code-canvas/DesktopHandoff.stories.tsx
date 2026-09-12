import type { Meta, StoryObj } from '@storybook/react'

import { DesktopHandoff, DesktopHandoffProps } from './DesktopHandoff'

type Story = StoryObj<DesktopHandoffProps>
const meta: Meta<DesktopHandoffProps> = {
    title: 'Scenes-Other/Desktop handoff',
    component: DesktopHandoff,
    args: {
        description: 'This task lives in the PostHog Desktop app.',
        view: 'code-task-link',
        onRetry: () => {},
    },
}
export default meta

export const Opening: Story = {
    args: { status: 'opening' },
}

export const Stalled: Story = {
    args: { status: 'stalled' },
}
