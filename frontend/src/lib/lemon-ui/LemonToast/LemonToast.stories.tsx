import { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { lemonToast, ToastCloseButton, ToastContent, ToastContentProps } from './LemonToast'

const meta: Meta<typeof ToastContent> = {
    title: 'Lemon UI/Lemon Toast',
    component: ToastContent,
    parameters: {
        testOptions: {
            include3000: true,
            waitForSelector: '.storybook-ready',
            waitForLoadersToDisappear: false,
            snapshotTargetSelector: '.Toastify__toast-container',
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
        const [isReady, setIsReady] = useState(true)

        useEffect(() => {
            lemonToast.dismiss()
            setIsReady(false)
            args.toasts.forEach((toast) => {
                const { type, message, ...rest } = toast
                lemonToast[type](message, { ...rest, containerId: isDarkModeOn ? 'dark' : 'light' })
            })
        }, [isDarkModeOn])

        return (
            <>
                {isDarkModeOn ? (
                    <ToastContainer
                        containerId="dark"
                        theme="dark"
                        enableMultiContainer
                        position="top-left" // different from app
                        autoClose={false} // different from app
                        transition={({ nodeRef, ...rest }) => {
                            setIsReady(
                                nodeRef.current !== null && !nodeRef.current.classList.contains('Toastify--animate')
                            )
                            return Slide({ nodeRef, ...rest })
                        }}
                        closeOnClick={false}
                        draggable={false}
                        closeButton={<ToastCloseButton />}
                    />
                ) : (
                    <ToastContainer
                        containerId="light"
                        theme="light"
                        enableMultiContainer
                        position="top-left" // different from app
                        autoClose={false} // different from app
                        transition={({ nodeRef, ...rest }) => {
                            setIsReady(
                                nodeRef.current !== null && !nodeRef.current.classList.contains('Toastify--animate')
                            )
                            return Slide({ nodeRef, ...rest })
                        }}
                        closeOnClick={false}
                        draggable={false}
                        closeButton={<ToastCloseButton />}
                    />
                )}

                <div className={isReady ? 'storybook-ready h-1 w-1 bg-primary-highlight absolute right-0' : ''} />
            </>
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

export const WithButton: Story = {
    ...ToastTypes,
    args: {
        toasts: [
            {
                type: 'success',
                message: 'Insight added to dashboard',
                button: {
                    label: 'View dashboard',
                    action: (): void => {},
                },
            },
        ],
    },
}

export const WithProgress: Story = {
    ...ToastTypes,
    args: {
        toasts: [
            {
                type: 'info',
                message: 'An info toast with progress',
                progress: 0.4,
            } as ToastContentProps,
            {
                type: 'success',
                message: 'A success toast with progress',
                progress: 0.4,
            } as ToastContentProps,
            {
                type: 'warning',
                message: 'A warning toast with progress',
                progress: 0.4,
            } as ToastContentProps,
            {
                type: 'error',
                message: 'An error toast with progress',
                progress: 0.4,
            } as ToastContentProps,
        ],
    },
}
