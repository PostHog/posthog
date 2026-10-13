import type { Meta, StoryObj } from '@storybook/react'
import { TrashIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import { Kbd } from './kbd'

const meta = {
    title: 'Primitives/Button',
    component: Button,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: [
                'default',
                'primary',
                'secondary',
                'outline',
                'destructive',
                'destructive-outline',
                'link',
                'link-muted',
            ],
        },
        size: {
            control: 'select',
            options: ['default', 'xs', 'sm', 'lg', 'icon', 'icon-xs', 'icon-sm', 'icon-lg'],
        },
        disabled: { control: 'boolean' },
        loading: { control: 'boolean' },
    },
} satisfies Meta<typeof Button>

export default meta
type Story = StoryObj<typeof meta>

export const Default = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button>Default</Button>
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="destructive-outline">Destructive outline</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="link">Link</Button>
        </div>
    ),
} satisfies Story

export const VariantDefault = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <div className="p-2">
                <Button>Default</Button>
                <Button aria-selected>Selected</Button>
                <Button disabled>Disabled</Button>
            </div>
            <div className="p-2 bg-muted">
                <Button>Default</Button>
                <Button aria-selected>Selected</Button>
                <Button disabled>Disabled</Button>
            </div>
        </div>
    ),
} satisfies Story

export const WithIcons = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button>
                <TrashIcon /> Default
            </Button>
            <Button variant="primary">
                <TrashIcon /> Primary
            </Button>
            <Button variant="secondary">
                <TrashIcon /> Secondary
            </Button>
            <Button variant="outline">
                <TrashIcon /> Outline
            </Button>
            <Button variant="destructive">
                <TrashIcon /> Destructive
            </Button>
            <Button variant="destructive-outline">
                <TrashIcon /> Destructive outline
            </Button>
            <Button variant="link">
                <TrashIcon /> Link
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
            <Button variant="secondary">
                Secondary
                <Kbd>⌘C</Kbd>
            </Button>
            <Button variant="outline">
                Outline
                <Kbd>⌘D</Kbd>
            </Button>
            <Button variant="destructive">
                Destructive
                <Kbd>⌘E</Kbd>
            </Button>
            <Button variant="destructive-outline">
                Destructive outline
                <Kbd>⌘F</Kbd>
            </Button>
            <Button variant="link">
                Link
                <Kbd>⌘G</Kbd>
            </Button>
        </div>
    ),
} satisfies Story

export const IconOnly = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Button size="icon">
                <TrashIcon />
            </Button>
            <Button variant="primary" size="icon">
                <TrashIcon />
            </Button>
            <Button variant="secondary" size="icon">
                <TrashIcon />
            </Button>
            <Button variant="outline" size="icon">
                <TrashIcon />
            </Button>
            <Button variant="destructive" size="icon">
                <TrashIcon />
            </Button>
            <Button variant="destructive-outline" size="icon">
                <TrashIcon />
            </Button>
            <Button variant="link" size="icon">
                <TrashIcon />
            </Button>
        </div>
    ),
} satisfies Story

export const InteractionStates = {
    parameters: {
        pseudo: {
            hover: ['#secondary-hover', '#destructive-outline-hover'],
            active: '#destructive-outline-active',
            focusVisible: '#destructive-outline-focus',
        },
    },
    render: () => (
        <div className="flex flex-col gap-2 items-start">
            <div className="flex flex-wrap gap-2">
                <Button variant="secondary">Secondary resting</Button>
                <Button id="secondary-hover" variant="secondary">
                    Secondary hover
                </Button>
            </div>
            <div className="flex flex-wrap gap-2">
                <Button variant="destructive-outline">Destructive outline resting</Button>
                <Button id="destructive-outline-hover" variant="destructive-outline">
                    Destructive outline hover
                </Button>
                <Button id="destructive-outline-active" variant="destructive-outline">
                    Destructive outline active
                </Button>
                <Button id="destructive-outline-focus" variant="destructive-outline">
                    Destructive outline focus
                </Button>
            </div>
        </div>
    ),
} satisfies Story

export const Sizes = {
    render: () => (
        <div className="grid grid-cols-[70px_30px_100px] gap-x-4 gap-y-2 items-center justify-items-start">
            <Button size="lg">Large</Button>
            <Button size="icon-lg">
                <TrashIcon />
            </Button>
            <Button size="lg">
                <TrashIcon />
                With icon
            </Button>

            <Button size="default">Default</Button>
            <Button size="icon">
                <TrashIcon />
            </Button>
            <Button size="default">
                <TrashIcon />
                With icon
            </Button>

            <Button size="sm">Small</Button>
            <Button size="icon-sm">
                <TrashIcon />
            </Button>
            <Button size="sm">
                <TrashIcon />
                With icon
            </Button>

            <Button size="xs">Extra small</Button>
            <Button size="icon-xs">
                <TrashIcon />
            </Button>
            <Button size="xs">
                <TrashIcon />
                With icon
            </Button>
        </div>
    ),
} satisfies Story

export const Disabled = {
    render: () => (
        <div className="flex flex-wrap items-center gap-2">
            <Button disabled>Default</Button>
            <Button variant="primary" disabled>
                Primary
            </Button>
            <Button variant="secondary" disabled>
                Secondary
            </Button>
            <Button variant="outline" disabled>
                Outline
            </Button>
            <Button variant="destructive" disabled>
                Destructive
            </Button>
            <Button variant="destructive-outline" disabled>
                Destructive outline
            </Button>
            <Button variant="link" disabled>
                Link
            </Button>
        </div>
    ),
} satisfies Story

export const Loading = {
    render: () => {
        const [saving, setSaving] = useState(false)
        const simulateSave = (): void => {
            setSaving(true)
            setTimeout(() => setSaving(false), 2000)
        }
        return (
            <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center gap-2">
                    <Button loading>Default</Button>
                    <Button variant="primary" loading>
                        Primary
                    </Button>
                    <Button variant="secondary" loading>
                        Secondary
                    </Button>
                    <Button variant="outline" loading>
                        Outline
                    </Button>
                    <Button variant="destructive" loading>
                        Destructive
                    </Button>
                    <Button variant="destructive-outline" loading>
                        Destructive outline
                    </Button>
                    <Button size="icon" loading aria-label="Delete">
                        <TrashIcon />
                    </Button>
                </div>
                {/* Click to see the rest → loading transition; resolves after 2s. */}
                <div className="flex flex-wrap gap-2">
                    <Button variant="primary" loading={saving} onClick={simulateSave}>
                        Save changes
                    </Button>
                </div>
            </div>
        )
    },
} satisfies Story

export const Misc = {
    render: () => (
        <div className="max-w-sm">
            <Button left className="w-full">
                Aligned left
            </Button>
            <Button left className="w-full">
                <TrashIcon /> Aligned left
            </Button>
        </div>
    ),
} satisfies Story
