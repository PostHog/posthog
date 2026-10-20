import type { Meta, StoryObj } from '@storybook/react'
import { ArrowRightIcon, CheckIcon, FolderIcon, PlusIcon, XIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from './button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from './card'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from './empty'

const meta = {
    title: 'Primitives/Button/Elevated',
    component: Button,
    tags: ['autodocs'],
    args: { elevated: true },
    argTypes: {
        variant: { control: 'select', options: ['outline', 'primary'] },
        size: { control: 'select', options: ['default', 'lg', 'icon', 'icon-lg'] },
        disabled: { control: 'boolean' },
        loading: { control: 'boolean' },
    },
    parameters: {
        docs: {
            description: {
                component:
                    'Heavy edge and bottom ledge for the strongest action in an area. Two looks: `primary` and neutral `outline`. ' +
                    'Show one alone, or one primary beside one neutral. A third button in the row must be a flat `default` (ghost). ' +
                    'Never place an elevated button next to a flat button with chrome.',
            },
        },
    },
} satisfies Meta<typeof Button>

export default meta
type Story = StoryObj<typeof meta>

function ThemePanel({ dark, children }: { dark?: boolean; children: ReactNode }): React.ReactElement {
    return (
        <div
            className={`${dark ? 'dark' : ''} bg-background text-foreground flex-1 rounded-lg border border-border p-5`}
        >
            <div className="mb-4 text-xs font-medium text-muted-foreground">{dark ? 'Dark' : 'Light'}</div>
            {children}
        </div>
    )
}

function Rule({
    kind,
    label,
    children,
}: {
    kind: 'do' | 'dont'
    label: string
    children: ReactNode
}): React.ReactElement {
    return (
        <div className="flex flex-col gap-4 rounded-lg border border-border bg-background p-5">
            <div
                className={`flex items-center gap-1.5 text-xs font-medium ${
                    kind === 'do' ? 'text-success-foreground' : 'text-destructive-foreground'
                }`}
            >
                {kind === 'do' ? <CheckIcon className="size-3.5" /> : <XIcon className="size-3.5" />}
                {kind === 'do' ? 'Do' : "Don't"}: {label}
            </div>
            {children}
        </div>
    )
}

export const Playground = {
    args: { variant: 'primary', size: 'lg', children: 'New' },
} satisfies Story

export const Overview = {
    parameters: { layout: 'fullscreen' },
    render: () => (
        <div className="flex flex-col gap-4 bg-muted p-6 sm:flex-row">
            {[false, true].map((dark) => (
                <ThemePanel key={String(dark)} dark={dark}>
                    <div className="flex flex-col gap-5">
                        <Button elevated variant="outline" className="h-14 w-full text-xl">
                            <PlusIcon className="size-5" /> New
                        </Button>
                        <div className="flex flex-wrap items-center gap-3">
                            <Button elevated variant="outline" size="lg">
                                Save draft
                            </Button>
                            <Button elevated variant="primary" size="lg">
                                Launch <ArrowRightIcon />
                            </Button>
                        </div>
                    </div>
                </ThemePanel>
            ))}
        </div>
    ),
} satisfies Story

export const Variants = {
    render: () => (
        <div className="flex flex-col items-start gap-4">
            <Button elevated variant="outline" size="lg">
                <PlusIcon /> Neutral
            </Button>
            <Button elevated variant="primary" size="lg">
                <PlusIcon /> Primary
            </Button>
        </div>
    ),
} satisfies Story

export const Sizes = {
    render: () => (
        <div className="flex flex-col items-start gap-4">
            <Button elevated variant="outline" className="h-12 w-72 text-base">
                <PlusIcon className="size-5" /> Hero
            </Button>
            <Button elevated variant="outline" size="lg">
                <PlusIcon /> Large
            </Button>
            <Button elevated variant="outline">
                <PlusIcon /> Default
            </Button>
            <Button elevated variant="outline" size="icon-lg" aria-label="New">
                <PlusIcon />
            </Button>
        </div>
    ),
} satisfies Story

const STATES = [
    ['Rest', {}],
    ['Hover', { id: 'elevated-hover' }],
    ['Pressed', { id: 'elevated-active' }],
    ['Focus', { id: 'elevated-focus' }],
    ['Disabled', { disabled: true }],
    ['Loading', { loading: true }],
] as const

export const States = {
    parameters: {
        pseudo: {
            hover: ['#elevated-hover-outline', '#elevated-hover-primary'],
            active: ['#elevated-active-outline', '#elevated-active-primary'],
            focusVisible: ['#elevated-focus-outline', '#elevated-focus-primary'],
        },
    },
    render: () => (
        <div className="grid grid-cols-[repeat(3,auto)] items-end justify-start gap-x-4 gap-y-5">
            {(['outline', 'primary'] as const).flatMap((variant) =>
                STATES.map(([label, props]) => (
                    <div key={`${variant}-${label}`} className="flex flex-col items-center gap-2">
                        <Button
                            elevated
                            variant={variant}
                            size="lg"
                            {...props}
                            id={'id' in props ? `${props.id}-${variant}` : undefined}
                        >
                            <PlusIcon /> New
                        </Button>
                        <span className="text-xs text-muted-foreground">{label}</span>
                    </div>
                ))
            )}
        </div>
    ),
} satisfies Story

export const Pairing = {
    render: () => (
        <div className="grid max-w-3xl grid-cols-1 gap-4 md:grid-cols-2">
            <Rule kind="do" label="one alone">
                <div>
                    <Button elevated variant="primary" size="lg">
                        <PlusIcon /> New dashboard
                    </Button>
                </div>
            </Rule>
            <Rule kind="do" label="one primary beside one neutral">
                <div className="flex gap-2">
                    <Button elevated variant="outline" size="lg">
                        Save draft
                    </Button>
                    <Button elevated variant="primary" size="lg">
                        Launch
                    </Button>
                </div>
            </Rule>
            <Rule kind="do" label="third button is a flat default">
                <div className="flex gap-2">
                    <Button variant="default" size="lg">
                        Cancel
                    </Button>
                    <Button elevated variant="outline" size="lg">
                        Save draft
                    </Button>
                    <Button elevated variant="primary" size="lg">
                        Launch
                    </Button>
                </div>
            </Rule>
            <Rule kind="dont" label="elevated next to a flat outline">
                <div className="flex gap-2">
                    <Button variant="outline" size="lg">
                        Save draft
                    </Button>
                    <Button elevated variant="primary" size="lg">
                        Launch
                    </Button>
                </div>
            </Rule>
            <Rule kind="dont" label="three elevated in a row">
                <div className="flex gap-2">
                    <Button elevated variant="outline" size="lg">
                        Preview
                    </Button>
                    <Button elevated variant="outline" size="lg">
                        Save draft
                    </Button>
                    <Button elevated variant="primary" size="lg">
                        Launch
                    </Button>
                </div>
            </Rule>
            <Rule kind="dont" label="two primaries">
                <div className="flex gap-2">
                    <Button elevated variant="primary" size="lg">
                        Publish
                    </Button>
                    <Button elevated variant="primary" size="lg">
                        Launch
                    </Button>
                </div>
            </Rule>
            <Rule kind="dont" label="small sizes or dense rows">
                <div className="flex gap-1">
                    <Button elevated variant="outline" size="sm">
                        Filter
                    </Button>
                    <Button elevated variant="outline" size="sm">
                        Sort
                    </Button>
                </div>
            </Rule>
        </div>
    ),
} satisfies Story

export const InSidebar = {
    render: () => (
        <div className="flex w-60 flex-col gap-1 rounded-lg border border-border bg-background p-3">
            <Button elevated variant="outline" size="lg" className="mb-3 w-full">
                <PlusIcon /> New
            </Button>
            {['Home', 'Dashboards', 'Insights', 'Recordings'].map((item) => (
                <Button key={item} left className="w-full">
                    {item}
                </Button>
            ))}
        </div>
    ),
} satisfies Story

export const InEmptyState = {
    render: () => (
        <Empty className="max-w-md border border-border">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <FolderIcon />
                </EmptyMedia>
                <EmptyTitle>No dashboards yet</EmptyTitle>
                <EmptyDescription>Pin insights together to track what matters.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row justify-center gap-2">
                <Button elevated variant="outline" size="lg">
                    Use a template
                </Button>
                <Button elevated variant="primary" size="lg">
                    <PlusIcon /> New dashboard
                </Button>
            </EmptyContent>
        </Empty>
    ),
} satisfies Story

export const InCard = {
    render: () => (
        <Card className="max-w-sm">
            <CardHeader>
                <CardTitle>Ready to launch your survey?</CardTitle>
                <CardDescription>It goes live for 10% of users who match your targeting.</CardDescription>
            </CardHeader>
            <CardFooter className="justify-end gap-2">
                <Button elevated variant="outline" size="lg">
                    Save draft
                </Button>
                <Button elevated variant="primary" size="lg">
                    Launch <ArrowRightIcon />
                </Button>
            </CardFooter>
        </Card>
    ),
} satisfies Story
