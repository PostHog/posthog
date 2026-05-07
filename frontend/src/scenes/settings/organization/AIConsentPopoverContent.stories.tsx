import { Meta, StoryObj } from '@storybook/react'

import { AIConsentPopoverContent } from './AIConsentPopoverWrapper'

const meta: Meta<typeof AIConsentPopoverContent> = {
    title: 'Scenes-Other/Settings/Organization/AI Consent Popover',
    component: AIConsentPopoverContent,
    parameters: {
        layout: 'centered',
    },
}
export default meta

type Story = StoryObj<typeof AIConsentPopoverContent>

const noop = (): void => {}

export const Default: Story = {
    args: {
        onApprove: noop,
        onDismiss: noop,
        approvalDisabledReason: null,
    },
}

export const NonAdmin: Story = {
    args: {
        onApprove: noop,
        onDismiss: noop,
        approvalDisabledReason: 'Ask an admin or owner of MockHog to approve this',
    },
}

export const LongDisabledReason: Story = {
    args: {
        onApprove: noop,
        onDismiss: noop,
        approvalDisabledReason:
            'Only organization owners and admins can approve AI data processing for MockHog. Ask Alice, Bob, or Carol to approve this for your team so you can start using PostHog AI features.',
    },
}
