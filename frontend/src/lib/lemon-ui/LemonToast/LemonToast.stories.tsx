import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { lemonToast, ToastCloseButton, ToastContent, ToastContentProps } from './LemonToast'

const meta: Meta<typeof ToastContent> = {
    title: 'Lemon UI/Lemon Toast',
    component: ToastContent,
    parameters: {
        testOptions: {
            include3000: true,
            waitForLoadersToDisappear: false,
            // waitForSelector
        },
    },
}

type ToastStory = {
    toasts: ToastContentProps[]
}

export default meta
type Story = StoryObj<ToastStory>

export const ToastTypes: Story = {
    args: {
        toasts: [
            {
                type: 'info',
                message: 'An info toast',
            },
            {
                type: 'success',
                message: 'A success toast',
            },
            {
                type: 'warning',
                message: 'A warning toast',
            },
            {
                type: 'error',
                message: 'An error toast',
            },
        ],
    },
    render: (args, { globals }) => {
        const isDarkModeOn = globals.theme === 'dark'

        useEffect(() => {
            args.toasts.forEach((toast) => {
                lemonToast[toast.type](toast.message)
            })
        }, [])

        return (
            <ToastContainer
                position="top-left" // different from app
                autoClose={false} // different from app
                transition={Slide}
                closeOnClick={false}
                draggable={false}
                closeButton={<ToastCloseButton />}
                theme={isDarkModeOn ? 'dark' : 'light'}
            />
        )
    },
}

export const BillingError: Story = {
    ...ToastTypes,
    args: {
        toasts: [
            {
                type: 'error',
                message:
                    'Load experiment failed: This feature is part of the premium PostHog offering. To use it, subscribe to PostHog Cloud with a generous free tier: https://app.posthog.com/organization/billing',
            },
        ],
    },
}
