import type { Meta, StoryObj } from '@storybook/react'

import { Text } from './text'

const meta = {
    title: 'Typography/Text',
    component: Text,
    tags: ['autodocs'],
    argTypes: {
        size: {
            control: 'select',
            options: ['lg', 'base', 'sm', 'xs', 'xxs'],
        },
        variant: {
            control: 'select',
            options: ['default', 'muted', 'destructive'],
        },
        weight: {
            control: 'select',
            options: ['normal', 'medium', 'semibold'],
        },
    },
} satisfies Meta<typeof Text>

export default meta
type Story = StoryObj<typeof meta>

export const Sizes = {
    render: () => (
        <div className="flex flex-col gap-2">
            <Text size="lg">Text lg</Text>
            <Text size="base">Text base</Text>
            <Text size="sm">Text sm</Text>
            <Text size="xs">Text xs</Text>
            <Text size="xxs">Text xxs</Text>
        </div>
    ),
} satisfies Story

export const Variants = {
    render: () => (
        <div className="flex flex-col gap-2">
            <Text variant="default">Default body text</Text>
            <Text variant="muted">Muted caption text</Text>
            <Text variant="destructive">Destructive error text</Text>
        </div>
    ),
} satisfies Story

export const Weights = {
    render: () => (
        <div className="flex flex-col gap-2">
            <Text weight="normal">Normal weight</Text>
            <Text weight="medium">Medium weight</Text>
            <Text weight="semibold">Semibold weight</Text>
        </div>
    ),
} satisfies Story

export const Inline = {
    render: () => (
        <Text>
            Body copy with an{' '}
            <Text render={<span />} weight="semibold">
                inline emphasis
            </Text>{' '}
            and a{' '}
            <Text render={<span />} variant="muted">
                muted aside
            </Text>
            .
        </Text>
    ),
} satisfies Story
