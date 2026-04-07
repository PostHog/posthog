import type { Meta, StoryObj } from '@storybook/react-vite'

import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from './field'
import { Input } from './input'

const meta = {
    title: 'Primitives/Field',
    component: Field,
    tags: ['autodocs'],
} satisfies Meta<typeof Field>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Field className="max-w-sm">
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input placeholder="Enter your username" id="username" />
        </Field>
    ),
} satisfies Story

export const Horizontal: Story = {
    render: () => (
        <Field orientation="horizontal" className="max-w-sm">
            <FieldLabel htmlFor="name">Name</FieldLabel>
            <FieldContent>
                <Input placeholder="Enter your name" id="name" />
                <FieldDescription>Helper text</FieldDescription>
            </FieldContent>
        </Field>
    ),
} satisfies Story

export const WithDescription: Story = {
    render: () => (
        <Field className="max-w-sm">
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input placeholder="Enter your username" id="username" />
            <FieldDescription>Optional helper text.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const Invalid: Story = {
    render: () => (
        <Field className="max-w-sm" data-invalid>
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input placeholder="Enter your username" id="username" aria-invalid />
            <FieldDescription>Optional helper text.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const InvalidWithError: Story = {
    render: () => (
        <Field className="max-w-sm" data-invalid>
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input placeholder="Enter your username" id="username" aria-invalid />
            <FieldDescription>Optional helper text.</FieldDescription>
            <FieldError>Validation message.</FieldError>
        </Field>
    ),
} satisfies Story
