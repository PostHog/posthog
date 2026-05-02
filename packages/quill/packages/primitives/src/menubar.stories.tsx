import type { Meta, StoryObj } from '@storybook/react'
import { Copy, Pencil, TrashIcon } from 'lucide-react'
import { useState } from 'react'

import { Kbd } from './kbd'
import {
    Menubar,
    MenubarCheckboxItem,
    MenubarContent,
    MenubarItem,
    MenubarLabel,
    MenubarMenu,
    MenubarRadioGroup,
    MenubarRadioItem,
    MenubarSeparator,
    MenubarSub,
    MenubarSubContent,
    MenubarSubTrigger,
    MenubarTrigger,
} from './menubar'

const meta = {
    title: 'Primitives/Menubar',
    component: Menubar,
    tags: ['autodocs'],
} satisfies Meta<typeof Menubar>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Menubar>
            <MenubarMenu>
                <MenubarTrigger>File</MenubarTrigger>
                <MenubarContent>
                    <MenubarItem>
                        <Copy />
                        New file
                        <Kbd>⌘N</Kbd>
                    </MenubarItem>
                    <MenubarItem>
                        <Pencil />
                        Rename
                    </MenubarItem>
                    <MenubarSeparator />
                    <MenubarItem variant="destructive">
                        <TrashIcon />
                        Delete
                    </MenubarItem>
                </MenubarContent>
            </MenubarMenu>
            <MenubarMenu>
                <MenubarTrigger>Edit</MenubarTrigger>
                <MenubarContent>
                    <MenubarItem>Undo</MenubarItem>
                    <MenubarItem>Redo</MenubarItem>
                    <MenubarSeparator />
                    <MenubarSub>
                        <MenubarSubTrigger>Find</MenubarSubTrigger>
                        <MenubarSubContent>
                            <MenubarItem>Find in file</MenubarItem>
                            <MenubarItem>Find in project</MenubarItem>
                        </MenubarSubContent>
                    </MenubarSub>
                </MenubarContent>
            </MenubarMenu>
        </Menubar>
    ),
} satisfies Story

export const WithCheckboxAndRadio: Story = {
    render: () => {
        const [bold, setBold] = useState(true)
        const [size, setSize] = useState('medium')
        return (
            <Menubar>
                <MenubarMenu>
                    <MenubarTrigger>Format</MenubarTrigger>
                    <MenubarContent>
                        <MenubarLabel>Style</MenubarLabel>
                        <MenubarCheckboxItem checked={bold} onCheckedChange={setBold}>
                            Bold
                        </MenubarCheckboxItem>
                        <MenubarSeparator />
                        <MenubarLabel>Size</MenubarLabel>
                        <MenubarRadioGroup value={size} onValueChange={setSize}>
                            <MenubarRadioItem value="small">Small</MenubarRadioItem>
                            <MenubarRadioItem value="medium">Medium</MenubarRadioItem>
                            <MenubarRadioItem value="large">Large</MenubarRadioItem>
                        </MenubarRadioGroup>
                    </MenubarContent>
                </MenubarMenu>
            </Menubar>
        )
    },
} satisfies Story
