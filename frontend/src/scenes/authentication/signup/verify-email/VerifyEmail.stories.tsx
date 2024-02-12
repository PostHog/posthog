import { Meta, Story } from '@storybook/react'
import { useEffect } from 'react'

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
export const VerifyEmailPending: Story = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('pending')
        verifyEmailLogic.actions.setUuid('12345678')
    }, [])
    return <VerifyEmail />
}

export const VerifyingEmail: Story = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('verify')
    }, [])
    return <VerifyEmail />
}
VerifyingEmail.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const VerifyEmailSuccess: Story = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('success')
    }, [])
    return <VerifyEmail />
}

export const VerifyEmailInvalid: Story = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('invalid')
        verifyEmailLogic.actions.setUuid('12345678')
    }, [])
    return <VerifyEmail />
}
