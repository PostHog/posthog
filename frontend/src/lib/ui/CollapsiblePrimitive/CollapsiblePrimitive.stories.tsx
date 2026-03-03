import type { Meta } from '@storybook/react'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { CollapsiblePrimitive, CollapsiblePrimitiveContent, CollapsiblePrimitiveTrigger } from './CollapsiblePrimitive'

const meta = {
    title: 'UI/CollapsiblePrimitive',
    component: CollapsiblePrimitive,
    tags: ['autodocs'],
} satisfies Meta<typeof CollapsiblePrimitive>

export default meta

export function Default(): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="max-w-sm">
            <CollapsiblePrimitive open={open} onOpenChange={setOpen}>
                <CollapsiblePrimitiveTrigger
                    render={<ButtonPrimitive />}
                    className="flex items-center gap-2 w-full px-2 py-1.5 text-sm font-medium"
                >
                    <IconChevronRight className={cn('size-4 transition-transform duration-200', open && 'rotate-90')} />
                    Click to expand
                </CollapsiblePrimitiveTrigger>
                <CollapsiblePrimitiveContent>
                    <div className="px-2 py-3 text-sm text-secondary">
                        This content is revealed with a smooth height animation using Base UI's Collapsible component.
                    </div>
                </CollapsiblePrimitiveContent>
            </CollapsiblePrimitive>
        </div>
    )
}

export function DefaultOpen(): JSX.Element {
    const [open, setOpen] = useState(true)

    return (
        <div className="max-w-sm">
            <CollapsiblePrimitive open={open} onOpenChange={setOpen}>
                <CollapsiblePrimitiveTrigger
                    render={<ButtonPrimitive />}
                    className="flex items-center gap-2 w-full px-2 py-1.5 text-sm font-medium"
                >
                    <IconChevronRight className={cn('size-4 transition-transform duration-200', open && 'rotate-90')} />
                    Initially open
                </CollapsiblePrimitiveTrigger>
                <CollapsiblePrimitiveContent>
                    <div className="px-2 py-3 text-sm text-secondary">
                        This panel started open and can be collapsed by clicking the trigger.
                    </div>
                </CollapsiblePrimitiveContent>
            </CollapsiblePrimitive>
        </div>
    )
}

export function Multiple(): JSX.Element {
    const [openSections, setOpenSections] = useState<Record<string, boolean>>({})

    const sections = [
        { id: 'overview', title: 'Overview', content: 'High-level summary of the feature and its purpose.' },
        {
            id: 'details',
            title: 'Details',
            content:
                'Each section operates independently. Opening one does not close the others. The height animation transitions smoothly for content of any length.',
        },
        { id: 'settings', title: 'Settings', content: 'Configuration options live here.' },
    ]

    return (
        <div className="max-w-sm divide-y">
            {sections.map((section) => {
                const isOpen = openSections[section.id] ?? false
                return (
                    <CollapsiblePrimitive
                        key={section.id}
                        open={isOpen}
                        onOpenChange={(next) => setOpenSections((prev) => ({ ...prev, [section.id]: next }))}
                    >
                        <CollapsiblePrimitiveTrigger
                            render={<ButtonPrimitive />}
                            className="flex items-center gap-2 w-full px-2 py-1.5 text-sm font-medium"
                        >
                            <IconChevronRight
                                className={cn('size-4 transition-transform duration-200', isOpen && 'rotate-90')}
                            />
                            {section.title}
                        </CollapsiblePrimitiveTrigger>
                        <CollapsiblePrimitiveContent>
                            <div className="px-2 py-3 text-sm text-secondary">{section.content}</div>
                        </CollapsiblePrimitiveContent>
                    </CollapsiblePrimitive>
                )
            })}
        </div>
    )
}

export function Disabled(): JSX.Element {
    return (
        <div className="max-w-sm">
            <CollapsiblePrimitive disabled>
                <CollapsiblePrimitiveTrigger
                    render={<ButtonPrimitive />}
                    className="flex items-center gap-2 w-full px-2 py-1.5 text-sm font-medium disabled:opacity-50"
                >
                    <IconChevronRight className="size-4" />
                    Disabled trigger
                </CollapsiblePrimitiveTrigger>
                <CollapsiblePrimitiveContent>
                    <div className="px-2 py-3 text-sm text-secondary">This content cannot be reached.</div>
                </CollapsiblePrimitiveContent>
            </CollapsiblePrimitive>
        </div>
    )
}

export function CustomContent(): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="max-w-md">
            <CollapsiblePrimitive open={open} onOpenChange={setOpen}>
                <CollapsiblePrimitiveTrigger
                    render={<ButtonPrimitive />}
                    className="flex items-center gap-2 w-full px-2 py-1.5 text-sm font-medium"
                >
                    <IconChevronRight className={cn('size-4 transition-transform duration-200', open && 'rotate-90')} />
                    Code context
                </CollapsiblePrimitiveTrigger>
                <CollapsiblePrimitiveContent className="border-t">
                    <pre className="bg-surface-primary p-3 text-xs font-mono overflow-x-auto">
                        {`function greet(name: string) {
    console.log(\`Hello, \${name}!\`)
}

greet('PostHog')`}
                    </pre>
                </CollapsiblePrimitiveContent>
            </CollapsiblePrimitive>
        </div>
    )
}
