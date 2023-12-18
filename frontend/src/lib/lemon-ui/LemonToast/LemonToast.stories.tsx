import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'
import { ToastContainer } from 'react-toastify'

import { lemonToast, ToastContent, ToastContentProps } from './LemonToast'

const meta: Meta<typeof ToastContent> = {
    title: 'Lemon UI/Lemon Toast',
    component: ToastContent,
    tags: ['autodocs'],
    parameters: {
        testOptions: {
            include3000: true,
        },
    },
}

type ToastStory = {
    toasts: ToastContentProps[]
}

export default meta
type Story = StoryObj<ToastStory>

export const LemonToast: Story = {
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
    render: (args) => {
        useEffect(() => {
            args.toasts.forEach((toast) => {
                lemonToast[toast.type](toast.message)
            })
        }, [])
        return <ToastContainer position="top-left" autoClose={false} />
    },
}

export const ApiError: Story = {
    ...LemonToast,
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
