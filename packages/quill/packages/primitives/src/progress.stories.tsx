import type { Meta, StoryObj } from '@storybook/react'

import { Progress, ProgressLabel, ProgressValue } from './progress'

const meta: Meta<typeof Progress> = {
    title: 'Primitives/Progress',
    component: Progress,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <Progress value={56} className="w-full max-w-sm">
                <ProgressLabel>Upload progress</ProgressLabel>
                <ProgressValue />
            </Progress>
        )
    },
}
