import type { Meta, StoryObj } from '@storybook/react'

import { Checkbox } from './checkbox'
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from './field'
import { Label } from './label'

const meta = {
    title: 'Primitives/Checkbox',
    component: Checkbox,
    tags: ['autodocs'],
} satisfies Meta<typeof Checkbox>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Checkbox id="checkbox" />
    ),
} satisfies Story

export const WithFieldGroup: Story = {
    render: () => (
        <FieldGroup className="max-w-sm">
            <Field orientation="horizontal">
                <Checkbox id="checkbox" />
                <Label htmlFor="checkbox">Checkbox</Label>
            </Field>
        </FieldGroup>
    ),
} satisfies Story

export const WithFieldDescription: Story = {
    render: () => (
        <FieldGroup className="max-w-sm">
            <Field orientation="horizontal">
                <Checkbox id="terms-checkbox-2" name="terms-checkbox-2" defaultChecked />
                <FieldContent>
                    <FieldLabel htmlFor="terms-checkbox-2">Accept terms and conditions</FieldLabel>
                    <FieldDescription>By clicking this checkbox, you agree to the terms.</FieldDescription>
                </FieldContent>
            </Field>
        </FieldGroup>
    ),
} satisfies Story

export const WithFieldLabel: Story = {
    render: () => (
        <FieldLabel className="max-w-sm">
            <Field orientation="horizontal">
                <Checkbox id="toggle-checkbox-2" name="toggle-checkbox-2" />
                <FieldContent>
                    <FieldTitle>Enable notifications</FieldTitle>
                    <FieldDescription>You can enable or disable notifications at any time.</FieldDescription>
                </FieldContent>
            </Field>
        </FieldLabel>
    ),
} satisfies Story
