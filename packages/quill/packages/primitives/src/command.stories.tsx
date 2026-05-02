import type { Meta, StoryObj } from '@storybook/react'
import { CalendarIcon, Cog, Search, User } from 'lucide-react'

import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
    CommandShortcut,
} from './command'

const meta = {
    title: 'Primitives/Command',
    component: Command,
    tags: ['autodocs'],
} satisfies Meta<typeof Command>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Command className="rounded-lg border border-border w-[420px]">
            <CommandInput placeholder="Type a command or search…" />
            <CommandList>
                <CommandEmpty>No results found.</CommandEmpty>
                <CommandGroup heading="Suggestions">
                    <CommandItem>
                        <CalendarIcon />
                        Calendar
                    </CommandItem>
                    <CommandItem>
                        <Search />
                        Search
                        <CommandShortcut>⌘S</CommandShortcut>
                    </CommandItem>
                </CommandGroup>
                <CommandSeparator />
                <CommandGroup heading="Settings">
                    <CommandItem>
                        <User />
                        Profile
                    </CommandItem>
                    <CommandItem>
                        <Cog />
                        Settings
                        <CommandShortcut>⌘,</CommandShortcut>
                    </CommandItem>
                </CommandGroup>
            </CommandList>
        </Command>
    ),
} satisfies Story
