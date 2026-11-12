import { Meta, StoryObj } from '@storybook/react'

import { DidYouKnowToast } from './DidYouKnowToast'

const meta: Meta<typeof DidYouKnowToast> = {
    title: 'Components/Did You Know Toast',
    component: DidYouKnowToast,
    parameters: {
        layout: 'centered',
    },
    decorators: [
        (Story) => (
            <div className="max-w-md min-w-140 rounded-lg border border-primary bg-surface-primary p-3 shadow-lg">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof DidYouKnowToast>

export const SqlEditorShortcut: Story = {
    args: {
        payload: {
            title: 'Did you know?',
            description: 'Type sql anywhere in PostHog to open the SQL editor.',
        },
    },
}

export const WithAction: Story = {
    args: {
        payload: {
            title: 'Did you know?',
            description: 'You can create a reusable action from any event.',
            action: {
                label: 'Learn about actions',
                url: 'https://posthog.com/docs/data/actions',
            },
        },
    },
}
