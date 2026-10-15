import { Meta, StoryObj } from '@storybook/react'

import { SceneLoadError } from './SceneLoadError'

const meta: Meta<typeof SceneLoadError> = {
    title: 'Scenes-App/Scene Load Error',
    component: SceneLoadError,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof SceneLoadError>

export const Default: Story = {}
