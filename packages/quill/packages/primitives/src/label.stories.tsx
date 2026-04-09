import type { Meta, StoryObj } from '@storybook/react'

import { Checkbox } from './checkbox'
import { Field, FieldLabel } from './field'
import { Input } from './input'
import { Label } from './label'

const meta = {
    title: 'Primitives/Label',
    component: Label,
    tags: ['autodocs'],
} satisfies Meta<typeof Label>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="flex gap-2">
                <Checkbox id="terms" />
                <Label htmlFor="terms">Accept terms and conditions</Label>
            </div>
        )
    },
} satisfies Story

export const WithField: Story = {
    render: () => {
        return (
            <Field className="max-w-sm">
                <FieldLabel htmlFor="email">Your email address</FieldLabel>
                <Input id="email" />
            </Field>
        )
    },
} satisfies Story
