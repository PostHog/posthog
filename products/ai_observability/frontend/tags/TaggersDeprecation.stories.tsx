import type { Meta, StoryObj } from '@storybook/react'

import { TaggerCreationRetiredModal } from './TaggerCreationRetiredModal'
import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

const meta: Meta = {
    title: 'Scenes-App/LLM observability/Taggers deprecation',
    parameters: {
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj

export const Banner: Story = {
    render: () => (
        <div className="max-w-[60rem]">
            <TaggersDeprecationBanner />
        </div>
    ),
}

export const BannerNarrow: Story = {
    render: () => (
        // Roughly the scene width left by the nav sidebar plus an open side panel.
        <div className="max-w-[32rem]">
            <TaggersDeprecationBanner />
        </div>
    ),
}

export const CreationRetiredModal: Story = {
    render: () => <TaggerCreationRetiredModal isOpen onClose={() => {}} />,
}
