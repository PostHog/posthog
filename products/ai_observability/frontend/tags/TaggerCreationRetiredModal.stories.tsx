import type { Meta, StoryObj } from '@storybook/react'

import { TaggerCreationRetiredModal } from './TaggerCreationRetiredModal'

const meta: Meta<typeof TaggerCreationRetiredModal> = {
    title: 'Scenes-App/LLM observability/Tagger creation retired modal',
    component: TaggerCreationRetiredModal,
    parameters: {
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof TaggerCreationRetiredModal>

export const Default: Story = {
    args: { isOpen: true, onClose: () => {}, inline: true },
}

export const TurnBackOn: Story = {
    args: { isOpen: true, onClose: () => {}, action: 'enable', inline: true },
}
