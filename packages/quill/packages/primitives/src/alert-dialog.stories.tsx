import type { Meta, StoryObj } from '@storybook/react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from './alert-dialog'
import { Button } from './button'

const meta = {
    title: 'Primitives/AlertDialog',
    component: AlertDialog,
    tags: ['autodocs'],
} satisfies Meta<typeof AlertDialog>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <AlertDialog>
            <AlertDialogTrigger render={<Button variant="destructive" size="sm" />}>Delete project</AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete this project?</AlertDialogTitle>
                    <AlertDialogDescription>
                        This permanently deletes the project and all of its data. This action cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose render={<Button variant="destructive" />}>Delete project</AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    ),
} satisfies Story

/* Backdrop clicks don't dismiss (disablePointerDismissal) — resolve with an
   action or Esc. */
export const NoPointerDismissal: Story = {
    render: () => (
        <AlertDialog defaultOpen>
            <AlertDialogTrigger render={<Button variant="destructive" size="sm" />}>Revoke API key</AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Revoke this API key?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Applications using this key will stop working immediately. Try clicking the backdrop — the
                        dialog stays open until you choose.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose render={<Button variant="destructive" />}>Revoke key</AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    ),
} satisfies Story
