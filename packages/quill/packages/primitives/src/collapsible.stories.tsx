import type { Meta, StoryObj } from '@storybook/react'
import { DatabaseZapIcon, FolderOpenIcon, GlobeIcon, PaperclipIcon } from 'lucide-react'

import { Button } from './button'
import { Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger } from './collapsible'
import { Text } from './text'

const meta = {
    title: 'Primitives/Collapsible',
    component: Collapsible,
    tags: ['autodocs'],
} satisfies Meta<typeof Collapsible>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Collapsible className="max-w-sm">
            <CollapsibleTrigger>
                <p>Collapsible Trigger</p>
            </CollapsibleTrigger>
            <CollapsibleContent>
                <p>Collapsible Content</p>
            </CollapsibleContent>
        </Collapsible>
    ),
} satisfies Story

/* Icon-only trigger: only the chevron toggles; the label is its own link and
   the trailing count stays independently rendered. `ms-auto` keeps the count
   end-aligned in RTL, and the chevron mirrors direction automatically. */
export const IconTrigger: Story = {
    render: () => (
        <Collapsible className="max-w-60" variant="folder" defaultOpen>
            <CollapsibleHeader>
                {/* Rest icon swaps to the chevron when the row is hovered. */}
                <CollapsibleTrigger iconOnly icon={<DatabaseZapIcon />}>
                    Toggle sources
                </CollapsibleTrigger>
                {/* Full-row surface under the overlaid chevron — ps-6 clears it,
                    so hovering anywhere highlights the whole row. */}
                <Button variant="default" size="sm" left className="w-full ps-8">
                    Sources
                    <Text size="xs" variant="muted" render={<span />} className="ms-auto">
                        2
                    </Text>
                </Button>
            </CollapsibleHeader>
            {/* ps-4 lines the child icons up under the header label text. */}
            <CollapsibleContent className="ps-6">
                <ul className="flex flex-col gap-px">
                    {[
                        { icon: <GlobeIcon />, label: 'APIs', count: 1 },
                        { icon: <PaperclipIcon />, label: 'MCPs', count: 1 },
                        { icon: <FolderOpenIcon />, label: 'Local Folders', count: 0 },
                    ].map(({ icon, label, count }) => (
                        <li key={label} className="flex w-full items-center">
                            <Button variant="default" size="sm" left className="w-full">
                                {icon}
                                {label}
                                <Text size="xs" variant="muted" render={<span />} className="ms-auto">
                                    {count}
                                </Text>
                            </Button>
                        </li>
                    ))}
                </ul>
            </CollapsibleContent>
        </Collapsible>
    ),
} satisfies Story

export const Folder: Story = {
    render: () => (
        <Collapsible className="max-w-sm" variant="folder">
            <CollapsibleTrigger>
                <p>Collapsible Trigger</p>
            </CollapsibleTrigger>
            <CollapsibleContent>
                <Button left size="sm" className="w-full">A button here</Button>
                <Collapsible variant="folder">
                    <CollapsibleTrigger>
                        <p>Collapsible Trigger</p>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <Button left size="sm" className="w-full">A button here</Button>
                    </CollapsibleContent>
                </Collapsible>
                <Button left size="sm" className="w-full">A button here</Button>
            </CollapsibleContent>
        </Collapsible>
    ),
} satisfies Story
