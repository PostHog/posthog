import type { Meta, StoryObj } from '@storybook/react-vite'

import { Field, FieldDescription, FieldLabel } from './field'
import { Textarea } from './textarea'

const meta = {
    title: 'Primitives/Textarea',
    tags: ['autodocs'],
} satisfies Meta<typeof Textarea>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Field>
            <Textarea id="textarea-message" placeholder="Type your message here." />
        </Field>
    ),
} satisfies Story

export const WithLabel: Story = {
    render: () => (
        <Field>
            <FieldLabel htmlFor="textarea-message">Message</FieldLabel>
            <Textarea id="textarea-message" placeholder="Type your message here." />
        </Field>
    ),
} satisfies Story

export const WithDescription: Story = {
    render: () => (
        <Field>
            <FieldLabel htmlFor="textarea-message">Message</FieldLabel>
            <Textarea id="textarea-message" placeholder="Type your message here." />
            <FieldDescription>Enter your message below.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const Disabled: Story = {
    render: () => (
        <Field data-disabled>
            <FieldLabel htmlFor="textarea-message">Message</FieldLabel>
            <Textarea id="textarea-message" placeholder="Type your message here." disabled />
        </Field>
    ),
} satisfies Story

export const Invalid: Story = {
    render: () => (
        <Field data-invalid>
            <FieldLabel htmlFor="textarea-invalid">Message</FieldLabel>
            <Textarea id="textarea-invalid" placeholder="Type your message here." aria-invalid />
            <FieldDescription>Please enter a valid message.</FieldDescription>
        </Field>
    ),
} satisfies Story
