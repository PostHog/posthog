import type { Meta, StoryObj } from '@storybook/react'

import { Button } from './button'
import {
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from './dialog'
import { ScrollArea } from './scroll-area'

const meta = {
    title: 'Primitives/Dialog',
    component: Dialog,
    tags: ['autodocs'],
} satisfies Meta<typeof Dialog>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Dialog>
            <DialogTrigger render={<Button variant="outline" size="sm" />}>Open dialog</DialogTrigger>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Dialog title</DialogTitle>
                    <DialogDescription>This is a description of the dialog content.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <p>Dialog body content goes here.</p>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button variant="primary">Confirm</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ),
} satisfies Story

export const Nested: Story = {
    render: () => (
        <Dialog>
            <DialogTrigger render={<Button variant="outline" size="sm" />}>Open dialog</DialogTrigger>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Dialog title</DialogTitle>
                    <DialogDescription>This is a description of the dialog content.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <p>Dialog body content goes here.</p>
                    <Dialog>
                        <DialogTrigger render={<Button variant="outline" />}>Open nested dialog</DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle>Dialog title</DialogTitle>
                                <DialogDescription>This is a description of the dialog content.</DialogDescription>
                            </DialogHeader>
                            <DialogFooter>
                                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                                <Button variant="primary">Confirm</Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>

                </DialogBody>

                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button variant="primary">Confirm</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ),
} satisfies Story

export const ScrollableContent: Story = {
    render: () => (
        <Dialog>
            <DialogTrigger render={<Button variant="outline" size="sm" />}>Open dialog</DialogTrigger>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Dialog title</DialogTitle>
                </DialogHeader>
                <DialogBody render={<ScrollArea className="max-h-[50vh]" />}>
                    {Array.from({ length: 10 }).map((_, index) => (
                        <p key={index} className="mb-4 leading-normal">
                            Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
                        </p>
                    ))}
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button variant="primary">Confirm</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    ),
} satisfies Story
