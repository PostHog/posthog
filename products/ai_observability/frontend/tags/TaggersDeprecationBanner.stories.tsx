import type { Meta, StoryObj } from '@storybook/react'

import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

const meta: Meta<typeof TaggersDeprecationBanner> = {
    title: 'Scenes-App/LLM observability/Taggers deprecation banner',
    component: TaggersDeprecationBanner,
    parameters: {
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof TaggersDeprecationBanner>

export const Default: Story = {}
