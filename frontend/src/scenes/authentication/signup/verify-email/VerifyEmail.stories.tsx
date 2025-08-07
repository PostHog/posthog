import { Meta, Story } from '@storybook/react'

import { VerifyEmail } from './VerifyEmail'
import { verifyEmailLogic } from './verifyEmailLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const meta: Meta = {
    title: 'Scenes-Other/Verify Email',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
export const VerifyEmailPending: Story = () => {
    useOnMountEffect(() => {
        verifyEmailLogic.actions.setView('pending')
        verifyEmailLogic.actions.setUuid('12345678')
    })

    return <VerifyEmail />
}

export const VerifyingEmail: Story = () => {
    useOnMountEffect(() => {
        verifyEmailLogic.actions.setView('verify')
    })

    return <VerifyEmail />
}
VerifyingEmail.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const VerifyEmailSuccess: Story = () => {
    useOnMountEffect(() => {
        verifyEmailLogic.actions.setView('success')
    })

    return <VerifyEmail />
}

export const VerifyEmailInvalid: Story = () => {
    useOnMountEffect(() => {
        verifyEmailLogic.actions.setView('invalid')
        verifyEmailLogic.actions.setUuid('12345678')
    })

    return <VerifyEmail />
}
