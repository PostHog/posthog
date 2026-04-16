import { Meta, StoryObj } from '@storybook/react'

import { PreflightCheck } from './PreflightCheck'

const meta: Meta = {
    title: 'Scenes-Other/Preflight',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<{}>

export const Preflight: Story = {
    render: () => <PreflightCheck />,
}
