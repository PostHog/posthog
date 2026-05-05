import type { Meta, StoryObj } from '@storybook/react'
import { CalendarIcon, Cog, FileTextIcon, MoonIcon, SearchIcon, SunIcon, UserIcon } from 'lucide-react'
import * as React from 'react'

import {
    Autocomplete,
    AutocompleteCollection,
    AutocompleteContent,
    AutocompleteEmpty,
    AutocompleteGroup,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteLabel,
    AutocompleteList,
    AutocompleteStatus,
} from './autocomplete'
import { Button } from './button'
import { Dialog, DialogContent } from './dialog'
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent } from './empty'

const meta = {
    title: 'Primitives/Autocomplete',
    component: Autocomplete,
    tags: ['autodocs'],
} satisfies Meta<typeof Autocomplete>

export default meta
type Story = StoryObj<typeof meta>

const FRAMEWORKS = [
    'Next.js',
    'SvelteKit',
    'Nuxt.js',
    'Remix',
    'Astro',
    'Gatsby',
    'Solid Start',
    'Qwik City',
    'Fresh',
    'Hono',
    'Redwood',
] as const

/*
 * Default — search input + scrollable filtered list inside a popover
 * anchored to a Button trigger. Items rendered via function-as-child so
 * base-ui owns the filter pipeline. For sticky-footer "Create new" action
 * patterns, use the Combobox primitive (which has `ComboboxListFooter`).
 */
export const Default: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const [value, setValue] = React.useState('')
        const triggerRef = React.useRef<HTMLButtonElement>(null)
        return (
            <div className="max-w-xs">
                <Autocomplete
                    items={FRAMEWORKS}
                    open={open}
                    onOpenChange={setOpen}
                    value={value}
                    onValueChange={setValue}
                >
                    <Button ref={triggerRef} variant="outline" size="sm" onClick={() => setOpen((p) => !p)}>
                        Pick a framework
                    </Button>
                    <AutocompleteContent anchor={triggerRef}>
                        <AutocompleteInput placeholder="Search…" />
                        <AutocompleteEmpty>No frameworks match</AutocompleteEmpty>
                        <AutocompleteList>
                            {(item: (typeof FRAMEWORKS)[number]) => (
                                <AutocompleteItem key={item} value={item}>
                                    {item}
                                </AutocompleteItem>
                            )}
                        </AutocompleteList>
                    </AutocompleteContent>
                </Autocomplete>
            </div>
        )
    },
} satisfies Story

type Group = { label: string; items: readonly string[] }
const GROUPED: Group[] = [
    { label: 'Frontend', items: ['Next.js', 'SvelteKit', 'Nuxt.js', 'Remix', 'Astro'] },
    { label: 'Backend', items: ['Hono', 'Fastify', 'Express', 'NestJS', 'tRPC'] },
]

/*
 * Grouped items via the function-as-child + Collection pattern. base-ui
 * filters across all groups and prunes empty groups automatically. Each
 * group's items go through `<AutocompleteCollection>` so the filter knows
 * which leaf items to keep.
 */
export const Grouped: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const [value, setValue] = React.useState('')
        return (
            <div className="max-w-xs">
                <Autocomplete items={GROUPED} open={open} onOpenChange={setOpen} value={value} onValueChange={setValue}>
                    <AutocompleteInput placeholder="Search…" />
                    <AutocompleteContent>
                        <AutocompleteEmpty>No matches</AutocompleteEmpty>
                        <AutocompleteList>
                            {(group: Group) => (
                                <AutocompleteGroup key={group.label} items={group.items}>
                                    <AutocompleteLabel>{group.label}</AutocompleteLabel>
                                    <AutocompleteCollection>
                                        {(item: string) => (
                                            <AutocompleteItem key={item} value={item}>
                                                {item}
                                            </AutocompleteItem>
                                        )}
                                    </AutocompleteCollection>
                                </AutocompleteGroup>
                            )}
                        </AutocompleteList>
                    </AutocompleteContent>
                </Autocomplete>
            </div>
        )
    },
} satisfies Story

export const EmptyState: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const [value, setValue] = React.useState('xxxxx')
        return (
            <div className="max-w-xs">
                <Autocomplete
                    items={FRAMEWORKS}
                    open={open}
                    onOpenChange={setOpen}
                    value={value}
                    onValueChange={setValue}
                >
                    <AutocompleteInput placeholder="Search frameworks…" />
                    <AutocompleteContent>
                        <AutocompleteEmpty>No frameworks match</AutocompleteEmpty>
                        <AutocompleteList>
                            {(item: (typeof FRAMEWORKS)[number]) => (
                                <AutocompleteItem key={item} value={item}>
                                    {item}
                                </AutocompleteItem>
                            )}
                        </AutocompleteList>
                    </AutocompleteContent>
                </Autocomplete>
            </div>
        )
    },
} satisfies Story

/*
 * Command palette — Autocomplete used to filter command items that fire
 * actions on selection (Cmd+K pattern). Hosted inside a Dialog for the
 * full-screen modal feel. Selection runs the command's `onRun` and
 * closes the palette via `onValueChange`.
 */
type Command = {
    id: string
    label: string
    section: 'General' | 'Theme' | 'Navigation'
    icon: React.ReactNode
    keywords?: string
    onRun: () => void
    endNode?: React.ReactNode
}

const COMMANDS: Command[] = [
    { id: 'open-settings', label: 'Open settings', section: 'General', icon: <Cog />, onRun: () => alert('open settings'), endNode: '' },
    { id: 'open-profile', label: 'Open profile', section: 'General', icon: <UserIcon />, onRun: () => alert('open profile'), endNode: '' },
    { id: 'new-doc', label: 'New document', section: 'General', icon: <FileTextIcon />, keywords: 'create file', onRun: () => alert('new doc'), endNode: '' },
    { id: 'theme-light', label: 'Switch to light theme', section: 'Theme', icon: <SunIcon />, onRun: () => alert('light theme'), endNode: '' },
    { id: 'theme-dark', label: 'Switch to dark theme', section: 'Theme', icon: <MoonIcon />, onRun: () => alert('dark theme'), endNode: '' },
    { id: 'go-calendar', label: 'Go to calendar', section: 'Navigation', icon: <CalendarIcon />, onRun: () => alert('calendar') },
    { id: 'go-search', label: 'Search everywhere', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('search'), endNode: '' },
    { id: 'go-x', label: 'Go to x', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('x') },
    { id: 'go-y', label: 'Go to y', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('y') },
    { id: 'go-z', label: 'Go to z', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('z') },
    { id: 'go-a', label: 'Go to a', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('a') },
    { id: 'go-b', label: 'Go to b', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('b') },
    { id: 'go-c', label: 'Go to c', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('c') },
    { id: 'go-d', label: 'Go to d', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('d') },
    { id: 'go-e', label: 'Go to e', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('e') },
    { id: 'go-f', label: 'Go to f', section: 'Navigation', icon: <SearchIcon />, onRun: () => alert('f') },
]

/*
 * CommandPalette uses the grouped function-as-child + Collection pattern
 * so base-ui can filter across sections. The sections array goes into
 * `items={...}` on Root, then each Group renders a `<AutocompleteCollection>`
 * over its commands. base-ui prunes commands and groups that don't match
 * the input. Selection is intercepted by `onValueChange` to fire the
 * command's `onRun` and dismiss the dialog.
 */
type CommandSection = { label: string; items: Command[] }

const SECTIONS: CommandSection[] = [
    { label: 'General', items: COMMANDS.filter((c) => c.section === 'General') },
    { label: 'Theme', items: COMMANDS.filter((c) => c.section === 'Theme') },
    { label: 'Navigation', items: COMMANDS.filter((c) => c.section === 'Navigation') },
]

export const CommandPalette: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const [query, setQuery] = React.useState('')

        const handleSelect = (id: string | null): void => {
            if (id === null) {return}
            const cmd = COMMANDS.find((c) => c.id === id)
            if (!cmd) {return}
            cmd.onRun()
            setOpen(false)
            setQuery('')
        }

        return (
            <>
                <Button variant="outline" onClick={() => setOpen(true)}>
                    Open palette ⌘K
                </Button>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogContent className="p-0 gap-0 max-h-[40vh]" showCloseButton={false}>
                        <Autocomplete
                            inline
                            items={SECTIONS}
                            value={query}
                            onValueChange={(val) => {
                                if (typeof val === 'string') {
                                    setQuery(val)
                                }
                            }}
                            onItemHighlighted={(item) => {
                                // hook for future analytics/preview
                                void item
                            }}
                        >
                            <AutocompleteInput placeholder="Type a command…" showClear>
                                <Button variant="outline" size="xs">Some more content</Button>
                            </AutocompleteInput>
                            <AutocompleteStatus emptyContent={<span>No commands match <strong>"{query}"</strong></span>}/>
                            <AutocompleteList>
                                {(section: CommandSection) => (
                                    <AutocompleteGroup key={section.label} items={section.items}>
                                        <AutocompleteLabel>{section.label}</AutocompleteLabel>
                                        <AutocompleteCollection>
                                            {(cmd: Command) => (
                                                <AutocompleteItem
                                                    key={cmd.id}
                                                    value={cmd.id}
                                                    onClick={() => handleSelect(cmd.id)}
                                                    className="block"
                                                >
                                                    {cmd.icon}
                                                    {cmd.label}
                                                    <span className="font-mono ml-auto text-xs text-muted-foreground/80">
                                                        2 days ago
                                                    </span>
                                               
                                                </AutocompleteItem>
                                            )}
                                        </AutocompleteCollection>
                                    </AutocompleteGroup>
                                )}
                            </AutocompleteList>
                            <AutocompleteEmpty>
                                No commands match <strong>"{query}"</strong>
                            </AutocompleteEmpty>
                        </Autocomplete>
                    </DialogContent>
                </Dialog>
            </>
        )
    },
} satisfies Story

export const CommandPaletteCustomEmpty: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const [query, setQuery] = React.useState('asdfasdfasdf')

        const handleSelect = (id: string | null): void => {
            if (id === null) {return}
            const cmd = COMMANDS.find((c) => c.id === id)
            if (!cmd) {return}
            cmd.onRun()
            setOpen(false)
            setQuery('')
        }

        return (
            <>
                <Button variant="outline" onClick={() => setOpen(true)}>
                    Open palette ⌘K
                </Button>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogContent className="p-0 gap-0 max-h-[40vh]" showCloseButton={false}>
                        <Autocomplete
                            inline
                            items={SECTIONS}
                            value={query}
                            onValueChange={(val) => {
                                if (typeof val === 'string') {
                                    setQuery(val)
                                }
                            }}
                            onItemHighlighted={(item) => {
                                // hook for future analytics/preview
                                void item
                            }}
                        >
                            <AutocompleteInput placeholder="Type a command…" showClear>
                                <Button variant="outline" size="xs">Some more content</Button>
                            </AutocompleteInput>
                            <AutocompleteStatus emptyContent={
                                <Empty>
                                    <EmptyHeader>
                                        <EmptyMedia variant="icon">
                                            <SearchIcon />
                                        </EmptyMedia>
                                        <EmptyTitle>Oops, we couldn't find that.</EmptyTitle>
                                        <EmptyDescription>
                                            Try searching for something else.
                                        </EmptyDescription>
                                    </EmptyHeader>
                                    <EmptyContent className="flex-row justify-center gap-2">
                                        <Button variant="primary">Call to action</Button>
                                        <Button variant="outline">Secondary</Button>
                                    </EmptyContent>
                                </Empty>
                            }/>
                            <AutocompleteList>
                                {(section: CommandSection) => (
                                    <AutocompleteGroup key={section.label} items={section.items}>
                                        <AutocompleteLabel>{section.label}</AutocompleteLabel>
                                        <AutocompleteCollection>
                                            {(cmd: Command) => (
                                                <AutocompleteItem
                                                    key={cmd.id}
                                                    value={cmd.id}
                                                    onClick={() => handleSelect(cmd.id)}
                                                    className="block"
                                                >
                                                    {cmd.icon}
                                                    {cmd.label}
                                                    <span className="font-mono ml-auto text-xs text-muted-foreground/80">
                                                        2 days ago
                                                    </span>
                                               
                                                </AutocompleteItem>
                                            )}
                                        </AutocompleteCollection>
                                    </AutocompleteGroup>
                                )}
                            </AutocompleteList>
                            <AutocompleteEmpty>
                                No commands match <strong>"{query}"</strong>
                            </AutocompleteEmpty>
                        </Autocomplete>
                    </DialogContent>
                </Dialog>
            </>
        )
    },
} satisfies Story
