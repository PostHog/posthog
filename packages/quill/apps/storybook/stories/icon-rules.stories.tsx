import type { Meta, StoryObj } from '@storybook/react'
import {
    ArrowUpRight as ArrowUpRightIcon,
    ChevronDown as ChevronDownIcon,
    Copy as CopyIcon,
    Pencil as PencilIcon,
    Plus as PlusIcon,
    Share as ShareIcon,
    Trash as TrashIcon,
} from 'lucide-react'
import React, { useState } from 'react'

import {
    Button,
    Card,
    CardContent,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Text,
} from '../../../packages/primitives/src'

const meta = {
    title: 'Examples/Icon rules',
    tags: ['autodocs'],
    parameters: {
        docs: {
            description: {
                component:
                    'When a labelled button or menu item gets a leading icon, a trailing icon, an ellipsis, or nothing. Ask the questions in order and stop at the first yes. The same rule is in frontend/src/design.md.',
            },
        },
    },
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

interface Step {
    label?: string
    question: string
    outcome: string
    example: React.ReactElement
}

const STEPS: Step[] = [
    {
        question: 'Does it reveal options or navigate somewhere?',
        outcome: 'Trailing icon',
        example: (
            <Button variant="outline">
                Export
                <ChevronDownIcon />
            </Button>
        ),
    },
    {
        question: 'Is it an established, familiar symbol?',
        outcome: 'Leading icon',
        example: (
            <Button variant="outline">
                <PlusIcon />
                Create
            </Button>
        ),
    },
    {
        question: 'Is it in a group of actions?',
        outcome: 'Leading icon',
        example: (
            <Button variant="outline">
                <CopyIcon />
                Duplicate
            </Button>
        ),
    },
    {
        label: 'Then, on its own',
        question: 'Does it need more input before it can happen?',
        outcome: 'Add an ellipsis, with or without a leading icon',
        example: (
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline">Rename…</Button>
                <Button variant="outline">
                    <PencilIcon />
                    Rename…
                </Button>
            </div>
        ),
    },
]

export const DecisionOrder: Story = {
    render: () => (
        <div className="flex flex-col gap-2 w-full max-w-2xl">
            {STEPS.map((step, index) => (
                <Card key={step.question} size="sm">
                    <CardContent className="flex flex-wrap items-center gap-4">
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <Text size="xs" variant="muted">
                                {step.label ?? `Question ${index + 1}`}
                            </Text>
                            <Text size="sm">{step.question}</Text>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                            {step.example}
                            <Text size="xs" variant="muted">
                                Yes: {step.outcome.toLowerCase()}
                            </Text>
                        </div>
                    </CardContent>
                </Card>
            ))}
            <Card size="sm">
                <CardContent className="flex flex-wrap items-center gap-4">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <Text size="xs" variant="muted">
                            No icon and no ellipsis
                        </Text>
                        <Text size="sm">The label alone</Text>
                    </div>
                    <Button variant="primary">Publish</Button>
                </CardContent>
            </Card>
        </div>
    ),
}

export const InAButtonRow: Story = {
    render: () => (
        <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline">
                <CopyIcon />
                Duplicate
            </Button>
            <Button variant="outline">
                <ShareIcon />
                Share
            </Button>
            <Button variant="outline">
                Export
                <ChevronDownIcon />
            </Button>
            <Button variant="outline">Rename…</Button>
            <Button variant="link">
                View docs
                <ArrowUpRightIcon />
            </Button>
            <Button variant="primary">Publish</Button>
        </div>
    ),
}

export const InAMenu: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        return (
            <div className="h-80">
                <DropdownMenu open={open} onOpenChange={setOpen}>
                    <DropdownMenuTrigger render={<Button variant="outline" />}>
                        Actions
                        <ChevronDownIcon />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                        <DropdownMenuGroup>
                            <DropdownMenuItem>
                                <PlusIcon />
                                New dashboard
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                                <CopyIcon />
                                Duplicate
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                                <PencilIcon />
                                Rename…
                            </DropdownMenuItem>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>
                                    <ShareIcon />
                                    Export
                                </DropdownMenuSubTrigger>
                                <DropdownMenuSubContent>
                                    <DropdownMenuItem>PNG</DropdownMenuItem>
                                    <DropdownMenuItem>CSV</DropdownMenuItem>
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive">
                            <TrashIcon />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        )
    },
}
