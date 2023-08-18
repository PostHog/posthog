import { StoryObj, StoryFn, Meta } from '@storybook/react'
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

export const VerifyEmailPending: StoryFn = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('pending')
        verifyEmailLogic.actions.setUuid('12345678')
    }, [])
    return <VerifyEmail />
}

export const VerifyingEmail: StoryObj = {
    render: () => {
        useEffect(() => {
            verifyEmailLogic.actions.setView('verify')
        }, [])
        return <VerifyEmail />
    },

    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const VerifyEmailSuccess: StoryFn = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('success')
    }, [])
    return <VerifyEmail />
}

export const VerifyEmailInvalid: StoryFn = () => {
    useEffect(() => {
        verifyEmailLogic.actions.setView('invalid')
        verifyEmailLogic.actions.setUuid('12345678')
    }, [])
    return <VerifyEmail />
}
