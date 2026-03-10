import type { Meta } from '@storybook/react'
import { useState } from 'react'

import { IconClock, IconFolder, IconHome, IconSparkles, IconStar } from '@posthog/icons'

import { Collapsible } from './Collapsible'

const meta = {
    title: 'UI/Collapsible',
    component: Collapsible,
    tags: ['autodocs'],
} satisfies Meta<typeof Collapsible>

export default meta

export function MenuDefault(): JSX.Element {
    const [open, setOpen] = useState(true)

    return (
        <div className="max-w-xs bg-surface-secondary p-2">
            <Collapsible variant="menu" open={open} onOpenChange={setOpen}>
                <Collapsible.Trigger icon={<IconSparkles />}>PostHog AI</Collapsible.Trigger>
                <Collapsible.Panel>
                    <div className="px-2 py-1 text-sm">New chat</div>
                    <div className="px-2 py-1 text-sm">Recent conversation 1</div>
                    <div className="px-2 py-1 text-sm">Recent conversation 2</div>
                </Collapsible.Panel>
            </Collapsible>
        </div>
    )
}

export function MenuMultipleSections(): JSX.Element {
    const [sections, setSections] = useState<Record<string, boolean>>({
        ai: true,
        project: true,
        favorites: false,
    })

    const toggle = (key: string): void => setSections((prev) => ({ ...prev, [key]: !prev[key] }))

    return (
        <div className="max-w-xs bg-surface-secondary p-2 flex flex-col gap-2">
            <Collapsible variant="menu" open={sections.ai} onOpenChange={() => toggle('ai')}>
                <Collapsible.Trigger icon={<IconSparkles />}>PostHog AI</Collapsible.Trigger>
                <Collapsible.Panel>
                    <div className="px-2 py-1 text-sm">New chat</div>
                    <div className="px-2 py-1 text-sm">Recent conversation</div>
                </Collapsible.Panel>
            </Collapsible>

            <Collapsible variant="menu" open={sections.project} onOpenChange={() => toggle('project')}>
                <Collapsible.Trigger icon={<IconFolder />}>Project</Collapsible.Trigger>
                <Collapsible.Panel>
                    <div className="px-2 py-1 text-sm flex items-center gap-2">
                        <IconHome className="size-4" /> Home
                    </div>
                    <div className="px-2 py-1 text-sm flex items-center gap-2">
                        <IconClock className="size-4" /> Activity
                    </div>
                </Collapsible.Panel>
            </Collapsible>

            <Collapsible variant="menu" open={sections.favorites} onOpenChange={() => toggle('favorites')}>
                <Collapsible.Trigger icon={<IconStar />}>Starred</Collapsible.Trigger>
                <Collapsible.Panel>
                    <div className="px-2 py-1 text-sm">Favorite item 1</div>
                    <div className="px-2 py-1 text-sm">Favorite item 2</div>
                </Collapsible.Panel>
            </Collapsible>
        </div>
    )
}

export function ContainerDefault(): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="max-w-md">
            <Collapsible variant="container" open={open} onOpenChange={setOpen}>
                <Collapsible.Trigger>
                    <span className="font-medium">handleRequest</span>
                    <span className="font-light px-1">app/server.ts@42:10</span>
                </Collapsible.Trigger>
                <Collapsible.Panel>
                    <pre className="bg-surface-primary text-xs font-mono overflow-x-auto">
                        {`function handleRequest(req, res) {
    const data = parseBody(req)
    return res.json({ ok: true })
}`}
                    </pre>
                </Collapsible.Panel>
            </Collapsible>
        </div>
    )
}

export function ContainerExpanded(): JSX.Element {
    const [open, setOpen] = useState(true)

    return (
        <div className="max-w-md">
            <Collapsible variant="container" open={open} onOpenChange={setOpen}>
                <Collapsible.Trigger>
                    <span className="font-medium">processEvent</span>
                    <span className="font-light px-1">worker/index.ts@18:5</span>
                </Collapsible.Trigger>
                <Collapsible.Panel>
                    <pre className="bg-surface-primary text-xs font-mono overflow-x-auto">
                        {`async function processEvent(event) {
    await validate(event)
    await store(event)
}`}
                    </pre>
                </Collapsible.Panel>
            </Collapsible>
        </div>
    )
}

export function ContainerDisabled(): JSX.Element {
    return (
        <div className="max-w-md">
            <Collapsible variant="container">
                <Collapsible.Trigger disabled>
                    <span className="font-medium">vendorFrame</span>
                    <span className="font-light px-1">node_modules/lib.js@1:0</span>
                </Collapsible.Trigger>
                <Collapsible.Panel>
                    <div className="p-3 text-xs text-secondary">No source available.</div>
                </Collapsible.Panel>
            </Collapsible>
        </div>
    )
}
