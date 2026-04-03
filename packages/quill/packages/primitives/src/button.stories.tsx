import type { Meta, StoryObj } from '@storybook/react-vite'
import { IconTrash } from '@posthog/icons'

import { Button } from './button'
import { Kbd } from './kbd'

const meta = {
    title: 'Primitives/Button',
    component: Button,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: ['default', 'primary', 'outline', 'destructive', 'link', 'link-muted'],
        },
        size: {
            control: 'select',
            options: ['default', 'xs', 'sm', 'lg', 'icon', 'icon-xs', 'icon-sm', 'icon-lg'],
        },
        disabled: { control: 'boolean' },
    },
} satisfies Meta<typeof Button>

export default meta
type Story = StoryObj<typeof meta>

export const Default = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button>Default</Button>
            <Button variant="primary">Primary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="link">Link</Button>
        </div>
    ),
} satisfies Story

export const WithIcons = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button>
                <IconTrash /> Default
            </Button>
            <Button variant="primary">
                <IconTrash /> Primary
            </Button>
            <Button variant="outline">
                <IconTrash /> Outline
            </Button>
            <Button variant="destructive">
                <IconTrash /> Destructive
            </Button>
            <Button variant="link">
                <IconTrash /> Link
            </Button>
        </div>
    ),
} satisfies Story
export const WithKBD = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button>
                Default
                <Kbd>⌘A</Kbd>
            </Button>
            <Button variant="primary">
                Primary
                <Kbd>⌘B</Kbd>
            </Button>
            <Button variant="outline">
                Outline
                <Kbd>⌘C</Kbd>
            </Button>
            <Button variant="destructive">
                Destructive
                <Kbd>⌘D</Kbd>
            </Button>
            <Button variant="link">
                Link
                <Kbd>⌘E</Kbd>
            </Button>
        </div>
    ),
} satisfies Story

export const IconOnly = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button size="icon">
                <IconTrash />
            </Button>
            <Button variant="primary" size="icon">
                <IconTrash />
            </Button>
            <Button variant="outline" size="icon">
                <IconTrash />
            </Button>
            <Button variant="destructive" size="icon">
                <IconTrash />
            </Button>
            <Button variant="link" size="icon">
                <IconTrash />
            </Button>
        </div>
    ),
} satisfies Story

export const Sizes = {
    render: () => (
        <div className="grid grid-cols-[70px_30px_100px] gap-x-4 gap-y-2 items-center justify-items-start">
            <Button size="lg">Large</Button>
            <Button size="icon-lg">
                <IconTrash />
            </Button>
            <Button size="lg">
                <IconTrash />
                With icon
            </Button>

            <Button size="default">Default</Button>
            <Button size="icon">
                <IconTrash />
            </Button>
            <Button size="default">
                <IconTrash />
                With icon
            </Button>

            <Button size="sm">Small</Button>
            <Button size="icon-sm">
                <IconTrash />
            </Button>
            <Button size="sm">
                <IconTrash />
                With icon
            </Button>

            <Button size="xs">Extra small</Button>
            <Button size="icon-xs">
                <IconTrash />
            </Button>
            <Button size="xs">
                <IconTrash />
                With icon
            </Button>
        </div>
    ),
} satisfies Story

export const Disabled = {
    render: () => (
        <div className="flex items-center gap-2">
            <Button disabled>
                Default
            </Button>
            <Button variant="primary" disabled>
                Primary
            </Button>
            <Button variant="outline" disabled>
                Outline
            </Button>
            <Button variant="destructive" disabled>
                Destructive
            </Button>
            <Button variant="link" disabled>
                Link
            </Button>
        </div>
    ),
} satisfies Story


export const Misc = {
    render: () => (
        <div className="max-w-sm">
            <Button left className="w-full">Aligned left</Button>
            <Button left className="w-full"><IconTrash /> Aligned left</Button>
        </div>
    ),
} satisfies Story