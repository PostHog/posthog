import type { Meta, StoryObj } from '@storybook/react'

import { Button } from './button'
import {
    Drawer,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    DrawerTrigger,
} from './drawer'
import { Field, FieldDescription, FieldLabel } from './field'
import { Input } from './input'

const meta = {
    title: 'Primitives/Drawer',
    component: Drawer,
    tags: ['autodocs'],
} satisfies Meta<typeof Drawer>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Drawer>
            <DrawerTrigger render={<Button variant="outline" />}>Open drawer</DrawerTrigger>
            <DrawerContent>
                <DrawerHeader>
                    <DrawerTitle>Drawer title</DrawerTitle>
                    <DrawerDescription>This is a description of the drawer content.</DrawerDescription>
                </DrawerHeader>
                <DrawerFooter>
                    <Button variant="primary">Confirm</Button>
                    <DrawerClose render={<Button variant="outline" />}>Cancel</DrawerClose>
                </DrawerFooter>
            </DrawerContent>
        </Drawer>
    ),
} satisfies Story

export const WithBody: Story = {
    render: () => (
        <Drawer>
            <DrawerTrigger render={<Button variant="outline" />}>Edit profile</DrawerTrigger>
            <DrawerContent>
                <DrawerHeader>
                    <DrawerTitle>Edit profile</DrawerTitle>
                    <DrawerDescription>
                        Make changes to your profile here. Click save when you&apos;re done.
                    </DrawerDescription>
                </DrawerHeader>
                <div className="flex flex-col gap-3 px-4">
                    <Field>
                        <FieldLabel htmlFor="drawer-name">Name</FieldLabel>
                        <Input id="drawer-name" defaultValue="Pedro Duarte" />
                    </Field>
                    <Field>
                        <FieldLabel htmlFor="drawer-username">Username</FieldLabel>
                        <Input id="drawer-username" defaultValue="@peduarte" />
                        <FieldDescription>Your public handle.</FieldDescription>
                    </Field>
                </div>
                <DrawerFooter>
                    <Button variant="primary">Save changes</Button>
                    <DrawerClose render={<Button variant="outline" />}>Cancel</DrawerClose>
                </DrawerFooter>
            </DrawerContent>
        </Drawer>
    ),
} satisfies Story

export const Left: Story = {
    render: () => (
        <Drawer swipeDirection="left">
            <DrawerTrigger render={<Button variant="outline" />}>Open from left</DrawerTrigger>
            <DrawerContent>
                <DrawerHeader>
                    <DrawerTitle>Navigation</DrawerTitle>
                    <DrawerDescription>Slides in from the left edge.</DrawerDescription>
                </DrawerHeader>
                <DrawerFooter>
                    <DrawerClose render={<Button variant="outline" />}>Close</DrawerClose>
                </DrawerFooter>
            </DrawerContent>
        </Drawer>
    ),
} satisfies Story

export const Right: Story = {
    render: () => (
        <Drawer swipeDirection="right">
            <DrawerTrigger render={<Button variant="outline" />}>Open from right</DrawerTrigger>
            <DrawerContent>
                <DrawerHeader>
                    <DrawerTitle>Details</DrawerTitle>
                    <DrawerDescription>Slides in from the right edge.</DrawerDescription>
                </DrawerHeader>
                <DrawerFooter>
                    <DrawerClose render={<Button variant="outline" />}>Close</DrawerClose>
                </DrawerFooter>
            </DrawerContent>
        </Drawer>
    ),
} satisfies Story

export const Top: Story = {
    render: () => (
        <Drawer swipeDirection="up">
            <DrawerTrigger render={<Button variant="outline" />}>Open from top</DrawerTrigger>
            <DrawerContent>
                <DrawerHeader>
                    <DrawerTitle>Announcement</DrawerTitle>
                    <DrawerDescription>Slides in from the top edge.</DrawerDescription>
                </DrawerHeader>
                <DrawerFooter>
                    <DrawerClose render={<Button variant="outline" />}>Close</DrawerClose>
                </DrawerFooter>
            </DrawerContent>
        </Drawer>
    ),
} satisfies Story
