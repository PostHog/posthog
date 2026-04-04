import type { Meta, StoryObj } from '@storybook/react-vite'
import { CheckIcon, Copy } from 'lucide-react'
import { useRef, useState } from 'react'

import { Button } from './button'
import { anchoredToast, toast, ToastCard, toastIconMap, ToastProvider } from './toast'

const meta = {
    title: 'Primitives/Toast',
    component: Button,
    tags: ['autodocs'],
    decorators: [
        (Story) => (
            <ToastProvider>
                <Story />
            </ToastProvider>
        ),
    ],
} satisfies Meta<typeof Button>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <div className="flex flex-col gap-2">
            <div>
                <Button onClick={() => toast({ title: 'Hello world' })}>Show toast</Button>
            </div>
            <div className="flex flex-col gap-2 max-w-[360px]">
                <ToastCard toastTitle="Title only" onDismiss={() => {}} />
                <ToastCard toastTitle="Title only, no dismiss" />
                <ToastCard toastDescription="Description only, no dismiss" />
                <ToastCard toastDescription="Description only, not really used" onDismiss={() => {}} />
                <ToastCard
                    toastTitle="Title and description"
                    toastDescription="The event has been removed."
                    onDismiss={() => {}}
                />
                <ToastCard
                    toastTitle="Title, description, and action"
                    toastDescription="The event has been removed."
                    onDismiss={() => {}}
                    action={{
                        label: 'Undo',
                        onClick: () => {},
                    }}
                />
                <ToastCard
                    toastTitle="Title and description, with icon"
                    toastDescription="The event has been removed."
                    icon={toastIconMap.success}
                    onDismiss={() => {}}
                />
                <ToastCard
                    toastTitle="Title and description, with icon and action"
                    toastDescription="The event has been removed."
                    icon={toastIconMap.success}
                    onDismiss={() => {}}
                    action={{
                        label: 'Undo',
                        onClick: () => {},
                    }}
                />
            </div>
        </div>
    ),
} satisfies Story

const longDescription = 'Some long description here to see how it wraps around the icon'

export const Types: Story = {
    render: () => {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => toast({ title: 'Default toast' })}>
                        Default
                    </Button>
                    <Button variant="outline" onClick={() => toast.success({ title: 'Operation completed' })}>
                        Success
                    </Button>
                    <Button variant="outline" onClick={() => toast.info({ title: 'Something to know' })}>
                        Info
                    </Button>
                    <Button variant="outline" onClick={() => toast.warning({ title: 'Be careful' })}>
                        Warning
                    </Button>
                    <Button variant="outline" onClick={() => toast.error({ title: 'Something went wrong' })}>
                        Error
                    </Button>
                    <Button variant="outline" onClick={() => toast.loading({ title: 'Processing...' })}>
                        Loading
                    </Button>
                </div>
                <div className="flex flex-wrap gap-2 w-[360px] [&>*]:w-full">
                    <ToastCard toastTitle="Default toast" toastDescription={longDescription} onDismiss={() => {}} />
                    <ToastCard
                        toastTitle="Success toast"
                        toastDescription={longDescription}
                        icon={toastIconMap.success}
                        onDismiss={() => {}}
                    />
                    <ToastCard
                        toastTitle="Info toast"
                        toastDescription={longDescription}
                        icon={toastIconMap.info}
                        onDismiss={() => {}}
                    />
                    <ToastCard
                        toastTitle="Warning toast"
                        toastDescription={longDescription}
                        icon={toastIconMap.warning}
                        onDismiss={() => {}}
                    />
                    <ToastCard
                        toastTitle="Error toast"
                        toastDescription={longDescription}
                        icon={toastIconMap.error}
                        onDismiss={() => {}}
                    />
                    <ToastCard
                        toastTitle="Loading toast"
                        toastDescription={longDescription}
                        icon={toastIconMap.loading}
                        onDismiss={() => {}}
                    />
                </div>
            </div>
        )
    },
} satisfies Story

export const WithTitle: Story = {
    render: () => (
        <div className="flex">
            <div className="flex flex-wrap gap-2">
                <Button
                    onClick={() =>
                        toast.success({
                            title: 'Changes saved',
                            description: 'Your settings have been updated successfully.',
                        })
                    }
                >
                    Success with title
                </Button>
                <Button
                    onClick={() =>
                        toast.error({
                            title: 'Upload failed',
                            description: 'The file could not be uploaded. Please try again.',
                        })
                    }
                >
                    Error with title
                </Button>
            </div>
        </div>
    ),
} satisfies Story

export const WithAction: Story = {
    render: () => {
        const [deleted, setDeleted] = useState(false)

        return (
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-3">
                    <Button
                        onClick={() => {
                            setDeleted(true)
                            toast.success({
                                title: 'Event deleted',
                                description: 'The event has been removed.',
                                onClose: () => setDeleted(false),
                                action: {
                                    label: 'Undo',
                                    onClick: () => {
                                        toast.info({ title: 'Undone!' })
                                    },
                                },
                            })
                        }}
                        disabled={deleted}
                    >
                        Delete event
                    </Button>
                    <span className="text-xs text-muted-foreground">
                        {deleted ? 'Deleted (click Undo in toast)' : 'Not deleted'}
                    </span>
                </div>
            </div>
        )
    },
} satisfies Story

export const UpdateToast: Story = {
    render: () => (
        <Button
            onClick={() => {
                const id = toast.loading({ description: 'Uploading...' })
                setTimeout(() => {
                    toast.update(id, {
                        title: 'Upload complete',
                        description: 'Your file has been uploaded.',
                        type: 'success',
                    })
                }, 2000)
            }}
        >
            Upload (updates after 2s)
        </Button>
    ),
} satisfies Story

export const Anchored: Story = {
    render: () => {
        const buttonRef = useRef<HTMLButtonElement>(null)
        const [copied, setCopied] = useState(false)

        const handleCopy = (): void => {
            if (copied) {
                return
            }

            setCopied(true)
            navigator.clipboard.writeText('Copied text!')
            anchoredToast({
                description: 'Copied!',
                anchor: buttonRef.current,
                onClose: () => setCopied(false),
            })
        }

        return (
            <div className="flex items-center justify-center p-20">
                <Button ref={buttonRef} size="icon" variant="outline" onClick={handleCopy}>
                    <span className="relative flex items-center justify-center">
                        <Copy
                            className="size-3.5 absolute transition-[opacity,filter] duration-150 ease-out"
                            style={{ opacity: copied ? 0 : 1, filter: copied ? 'blur(4px)' : 'blur(0px)' }}
                        />
                        <CheckIcon
                            className="size-3.5 absolute transition-[opacity,filter] duration-150 ease-out"
                            style={{ opacity: copied ? 1 : 0, filter: copied ? 'blur(0px)' : 'blur(4px)' }}
                        />
                    </span>
                </Button>
            </div>
        )
    },
} satisfies Story

export const Dismiss: Story = {
    render: () => {
        const toastIdRef = useRef<string | undefined>(undefined)
        const [clicked, setClicked] = useState(false)

        return (
            <div className="flex flex-wrap gap-2">
                <Button
                    onClick={() => {
                        toastIdRef.current = toast.loading({ description: 'This stays until dismissed' })
                        setClicked(true)
                    }}
                    disabled={clicked}
                >
                    Show persistent toast
                </Button>
                <Button
                    variant="outline"
                    onClick={() => {
                        if (toastIdRef.current) {
                            toast.dismiss(toastIdRef.current)
                            toastIdRef.current = undefined
                        }
                        setClicked(false)
                    }}
                >
                    Dismiss
                </Button>
            </div>
        )
    },
} satisfies Story
