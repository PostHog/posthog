import type { Meta, StoryObj } from '@storybook/react'
import { SearchIcon } from 'lucide-react'
import { useState } from 'react'

import { Field, FieldDescription, FieldLabel } from './field'
import { Input } from './input'
import { InputGroup, InputGroupAddon, InputGroupInput } from './input-group'
import { cn } from './lib/utils'

const meta = {
    title: 'Primitives/Input',
    tags: ['autodocs'],
} satisfies Meta<typeof Input>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Field>
            <Input placeholder="Enter your text" id="text" />
        </Field>
    ),
} satisfies Story

export const WithLabel: Story = {
    render: () => (
        <Field>
            <FieldLabel htmlFor="text">Text</FieldLabel>
            <Input placeholder="Enter your text" id="text" />
        </Field>
    ),
} satisfies Story

export const WithDescription: Story = {
    render: () => (
        <Field>
            <FieldLabel htmlFor="username">Username</FieldLabel>
            <Input placeholder="Enter your username" id="username" />
            <FieldDescription>Choose a unique username for your account.</FieldDescription>
        </Field>
    ),
} satisfies Story

export const Password: Story = {
    render: () => (
        <Field>
            <FieldLabel htmlFor="password">Password</FieldLabel>
            <Input placeholder="Enter your password" type="password" id="password" />
        </Field>
    ),
} satisfies Story

export const Disabled: Story = {
    render: () => (
        <Field data-disabled>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input placeholder="Enter your email" id="email" disabled />
        </Field>
    ),
} satisfies Story

export const Invalid: Story = {
    render: () => (
        <Field data-invalid>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input placeholder="Enter your email" id="email" aria-invalid />
        </Field>
    ),
} satisfies Story

const EXAMPLES = ['createdBy:me', 'in:"Team Growth"', 'name:revenue', 'is:dashboard', 'is:feature-flag', 'is:insight']

function RotatingExample(): JSX.Element {
    // Counts every cycle, so only the very first example skips its fade-in.
    const [cycle, setCycle] = useState(0)
    return (
        <span
            key={cycle}
            className={cn('quill-fade-cycle', cycle === 0 && 'quill-fade-cycle--settled')}
            onAnimationEnd={() => setCycle((current) => current + 1)}
        >
            {EXAMPLES[cycle % EXAMPLES.length]}
        </span>
    )
}

/**
 * A placeholder that rotates examples. `InputGroupInput` takes a node as its `placeholder` and lays it out in the
 * input's own box, so it starts at the caret. `quill-fade-cycle` runs one cycle, and `onAnimationEnd` moves to the
 * next example. Type to hide it; reduced motion keeps the first example.
 */
export const AnimatedPlaceholder: Story = {
    render: () => (
        <Field>
            <InputGroup>
                <InputGroupAddon>
                    <SearchIcon />
                </InputGroupAddon>
                <InputGroupInput
                    aria-label="Search"
                    placeholder={
                        <>
                            Search… try&nbsp;
                            <RotatingExample />
                        </>
                    }
                />
            </InputGroup>
        </Field>
    ),
} satisfies Story
