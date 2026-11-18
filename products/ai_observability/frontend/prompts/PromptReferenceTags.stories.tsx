import type { Meta, StoryObj } from '@storybook/react'

import { PromptReferenceTags } from './PromptReferenceTags'

const meta: Meta<typeof PromptReferenceTags> = {
    title: 'Scenes-App/AI Observability/PromptReferenceTags',
    component: PromptReferenceTags,
}
export default meta

type Story = StoryObj<typeof PromptReferenceTags>

export const LabelAndVersionReferences: Story = {
    args: {
        text: 'Intro.\n@@@prompt:name=guardrails|label=production@@@\nMore text.\n@@@prompt:name=tone|version=3@@@',
    },
}
