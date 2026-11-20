import type { Meta, StoryObj } from '@storybook/react'

import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill-primitives'

import {
    Credenza,
    CredenzaBody,
    CredenzaClose,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    CredenzaTrigger,
} from './credenza'

const meta = {
    title: 'Components/Credenza',
    component: Credenza,
    tags: ['autodocs'],
} satisfies Meta<typeof Credenza>

export default meta
type Story = StoryObj<typeof meta>

// Resize the canvas below 768px to see the drawer.
export const Default: Story = {
    render: () => (
        <Credenza>
            <CredenzaTrigger render={<Button variant="outline" />}>Rename dashboard</CredenzaTrigger>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Rename dashboard</CredenzaTitle>
                    <CredenzaDescription>Everyone in the project sees the new name.</CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <Field>
                        <FieldLabel htmlFor="credenza-name">Name</FieldLabel>
                        <Input id="credenza-name" defaultValue="Weekly growth" />
                        <FieldDescription>Up to 400 characters.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <CredenzaClose render={<Button variant="outline" />}>Cancel</CredenzaClose>
                    <Button variant="primary">Save</Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    ),
} satisfies Story

const SECTIONS = Array.from({ length: 12 }, (_, index) => index + 1)

export const ScrollableContent: Story = {
    render: () => (
        <Credenza defaultOpen>
            <CredenzaTrigger render={<Button variant="outline" />}>Read changelog</CredenzaTrigger>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Changelog</CredenzaTitle>
                    <CredenzaDescription>What changed in the last 12 releases.</CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <div className="flex flex-col gap-3">
                        {SECTIONS.map((section) => (
                            <p key={section}>
                                Release {section} makes insights load faster, fixes the date picker on small screens,
                                and adds keyboard shortcuts to the dashboard toolbar.
                            </p>
                        ))}
                    </div>
                </CredenzaBody>
                <CredenzaFooter>
                    <CredenzaClose render={<Button variant="outline" />}>Close</CredenzaClose>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    ),
} satisfies Story
