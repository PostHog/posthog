import type { Meta, StoryObj } from '@storybook/react'

import { PersonalAPIKeyReveal, PersonalAPIKeyRevealProps } from './PersonalAPIKeyReveal'

type Story = StoryObj<PersonalAPIKeyRevealProps>
const meta: Meta<PersonalAPIKeyRevealProps> = {
    title: 'Scenes-App/Settings/Personal API Key Reveal',
    component: PersonalAPIKeyReveal,
    args: {
        label: 'Reports bot',
        value: 'phx_exampleValueThatIsShownExactlyOnce',
        onDone: () => {},
    },
}
export default meta

export const Created: Story = {}

export const Rolled: Story = {
    args: {
        rolledFromMaskValue: 'phx_...abcd',
    },
}
