import type { Meta, StoryObj } from '@storybook/react-vite'

import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel, FieldTitle } from './field'
import { Label } from './label'
import { Switch } from './switch'

const meta = {
    title: 'Primitives/Switch',
    component: Switch,
    tags: ['autodocs'],
} satisfies Meta<typeof Switch>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="flex items-center space-x-2">
                <Switch id="airplane-mode" />
                <Label htmlFor="airplane-mode">Airplane Mode</Label>
            </div>
        )
    },
} satisfies Story

export const Description: Story = {
    render: () => {
        return (
            <Field orientation="horizontal" className="max-w-sm">
                <FieldContent>
                    <FieldLabel htmlFor="switch-focus-mode">Share across devices</FieldLabel>
                    <FieldDescription>
                        Focus is shared across devices, and turns off when you leave the app.
                    </FieldDescription>
                </FieldContent>
                <Switch id="switch-focus-mode" />
            </Field>
        )
    },
} satisfies Story

export const ChoiceCard: Story = {
    render: () => {
        return (
            <FieldGroup className="w-full max-w-sm">
                <FieldLabel htmlFor="switch-share">
                    <Field orientation="horizontal">
                        <FieldContent>
                            <FieldTitle>Share across devices</FieldTitle>
                            <FieldDescription>
                                Focus is shared across devices, and turns off when you leave the app.
                            </FieldDescription>
                        </FieldContent>
                        <Switch id="switch-share" />
                    </Field>
                </FieldLabel>
                <FieldLabel htmlFor="switch-notifications">
                    <Field orientation="horizontal">
                        <FieldContent>
                            <FieldTitle>Enable notifications</FieldTitle>
                            <FieldDescription>
                                Receive notifications when focus mode is enabled or disabled.
                            </FieldDescription>
                        </FieldContent>
                        <Switch id="switch-notifications" defaultChecked />
                    </Field>
                </FieldLabel>
            </FieldGroup>
        )
    },
} satisfies Story

export const Disabled: Story = {
    render: () => {
        return (
            <Field orientation="horizontal" data-disabled className="w-fit">
                <Switch id="switch-disabled-unchecked" disabled />
                <FieldLabel htmlFor="switch-disabled-unchecked">Disabled</FieldLabel>
            </Field>
        )
    },
} satisfies Story

export const Invalid: Story = {
    render: () => {
        return (
            <Field orientation="horizontal" className="max-w-sm" data-invalid>
                <FieldContent>
                    <FieldLabel htmlFor="switch-terms">Accept terms and conditions</FieldLabel>
                    <FieldDescription>You must accept the terms and conditions to continue.</FieldDescription>
                </FieldContent>
                <Switch id="switch-terms" aria-invalid />
            </Field>
        )
    },
} satisfies Story
