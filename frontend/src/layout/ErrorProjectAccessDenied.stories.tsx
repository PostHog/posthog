import { Meta, StoryObj } from '@storybook/react'

import { ErrorProjectAccessDenied } from './ErrorProjectAccessDenied'

const meta: Meta<typeof ErrorProjectAccessDenied> = {
    title: 'Scenes-App/Error Project Access Denied',
    component: ErrorProjectAccessDenied,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof ErrorProjectAccessDenied>

export const Default: Story = {}
