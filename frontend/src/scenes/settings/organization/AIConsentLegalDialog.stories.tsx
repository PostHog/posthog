import { Meta, StoryObj } from '@storybook/react'

import { LemonDialog } from '@posthog/lemon-ui'

import { aiConsentLegalDialogProps } from './aiConsentCopy'

const noop = (): void => {}

const meta: Meta<typeof LemonDialog> = {
    title: 'Scenes-Other/Settings/Organization/AI Consent Legal Dialog',
    component: LemonDialog,
    parameters: {
        layout: 'centered',
    },
}
export default meta

type Story = StoryObj<typeof LemonDialog>

export const Default: Story = {
    render: () => (
        <div className="bg-default p-4">
            <LemonDialog {...aiConsentLegalDialogProps({ onConfirm: noop })} inline />
        </div>
    ),
}
