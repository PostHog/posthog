import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Button } from './button'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from './combobox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './dropdown-menu'
import { MenuEmpty } from './menu-empty'

const meta = {
    title: 'Primitives/Empty/MenuEmpty',
    component: MenuEmpty,
    tags: ['autodocs'],
} satisfies Meta<typeof MenuEmpty>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    Empty menu
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    <MenuEmpty>No items found</MenuEmpty>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}

export const InCombobox: Story = {
    render: () => {
        const frameworks = ['React', 'Vue', 'Angular', 'Svelte', 'Solid']
        return (
            <Combobox items={frameworks}>
                <ComboboxInput placeholder="Type 'xyz' to see empty state..." className="max-w-xs" />
                <ComboboxContent>
                    <ComboboxEmpty>No items found</ComboboxEmpty>
                    <ComboboxList>
                        {(item: string) => (
                            <ComboboxItem key={item} value={item}>
                                {item}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        )
    },
}

export const WithFilteredResults: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const items = ['Apple', 'Banana', 'Cherry']
        const filter = 'xyz'
        const filtered = items.filter((i) => i.toLowerCase().includes(filter))

        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    Filtered menu
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    {filtered.length > 0 ? (
                        filtered.map((item) => <DropdownMenuItem key={item}>{item}</DropdownMenuItem>)
                    ) : (
                        <MenuEmpty>No items found</MenuEmpty>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}
