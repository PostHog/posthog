import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { VerifyEmail } from './VerifyEmail'
import { verifyEmailLogic } from './verifyEmailLogic'

const meta: Meta = {
    title: 'Scenes-Other/Verify Email',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<{}>

export const VerifyEmailPending: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            verifyEmailLogic.actions.setView('pending')
            verifyEmailLogic.actions.setUuid('12345678')
        })

        return <VerifyEmail />
    },
}

export const VerifyingEmail: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            verifyEmailLogic.actions.setView('verify')
        })

        return <VerifyEmail />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const VerifyEmailSuccess: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            verifyEmailLogic.actions.setView('success')
        })

        return <VerifyEmail />
    },
}

export const VerifyEmailInvalid: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            verifyEmailLogic.actions.setView('invalid')
            verifyEmailLogic.actions.setUuid('12345678')
        })

        return <VerifyEmail />
    },
}
