import type { Meta, StoryObj } from '@storybook/react'

import { SupportPlaybookEditor } from './SupportPlaybookEditor'

const inherited = `You are drafting a support reply for this team's product. Do not assume the product is PostHog.

Tone:
- Be direct, friendly, and concise. Lead with the answer.`

const meta: Meta<typeof SupportPlaybookEditor> = {
    title: 'Scenes-App/Support/SupportPlaybookEditor',
    component: SupportPlaybookEditor,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof SupportPlaybookEditor>

export const DefaultInstructions: Story = {
    args: {
        inheritedInstructions: inherited,
        draft: '',
        isCustomized: false,
        maxChars: 8000,
        saving: false,
        loading: false,
        error: null,
        dirty: false,
        onDraftChange: () => {},
        onSave: () => {},
        onReset: () => {},
    },
}

export const Customized: Story = {
    args: {
        ...DefaultInstructions.args,
        isCustomized: true,
        draft: 'Always greet the customer by first name.',
        dirty: true,
    },
}

export const Loading: Story = {
    // The skeleton is the point of this story, so the snapshot cannot wait for it to go.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    args: {
        inheritedInstructions: '',
        draft: '',
        isCustomized: false,
        maxChars: 8000,
        saving: false,
        loading: true,
        error: null,
        dirty: false,
        onDraftChange: () => {},
        onSave: () => {},
        onReset: () => {},
    },
}

export const LoadError: Story = {
    args: {
        inheritedInstructions: '',
        draft: '',
        isCustomized: false,
        maxChars: 8000,
        saving: false,
        loading: false,
        error: "Couldn't load the support playbook. Refresh the page, and if it keeps happening contact support.",
        dirty: false,
        onDraftChange: () => {},
        onSave: () => {},
        onReset: () => {},
    },
}
