import type { Meta, StoryObj } from '@storybook/react'
import { Copy, Download, Ellipsis, Pencil, Trash2 } from 'lucide-react'
import * as React from 'react'

import { Button, Input } from '@posthog/quill-primitives'

import { ActionMenu } from './action-menu'
import type { ActionMenuItem } from './action-menu-tree'

const meta = {
    title: 'Components/ActionMenu',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

function useItems(): ActionMenuItem[] {
    const [pinned, setPinned] = React.useState(false)
    const [density, setDensity] = React.useState('standard')
    const [note, setNote] = React.useState('')
    return [
        {
            type: 'submenu',
            id: 'file',
            label: 'File',
            section: 'menus',
            items: [
                {
                    type: 'submenu',
                    id: 'export',
                    label: 'Export',
                    icon: <Download />,
                    items: [
                        { id: 'png', label: 'PNG', onSelect: () => {} },
                        { id: 'csv', label: 'CSV', onSelect: () => {} },
                    ],
                },
                {
                    id: 'copy',
                    label: 'Copy to another project',
                    icon: <Copy />,
                    section: 'project',
                    onSelect: () => {},
                },
                { id: 'delete', label: 'Delete insight', icon: <Trash2 />, destructive: true, onSelect: () => {} },
            ],
        },
        {
            type: 'submenu',
            id: 'edit',
            label: 'Edit',
            section: 'menus',
            items: [
                { id: 'rename', label: 'Rename', icon: <Pencil />, opensFloatingUi: true, onSelect: () => {} },
                {
                    type: 'radio',
                    id: 'density',
                    label: 'Tile density',
                    value: density,
                    options: [
                        { value: 'compact', label: 'Compact' },
                        { value: 'standard', label: 'Standard' },
                    ],
                    onValueChange: setDensity,
                },
                {
                    type: 'checkbox',
                    id: 'pinned',
                    label: 'Pinned',
                    section: 'toggles',
                    checked: pinned,
                    onCheckedChange: setPinned,
                },
            ],
        },
        {
            type: 'panel',
            id: 'metadata',
            label: 'Metadata',
            section: 'metadata',
            render: () => <Input placeholder="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />,
        },
    ]
}

// One search field over a short top level. Each menu opens a submenu; Delete sits last at the top level, whichever
// menu declares it. Type "csv" to see a result from two levels down, with its path.
export const Default: Story = {
    render: function Render() {
        return (
            <ActionMenu
                items={useItems()}
                trigger={<Button size="icon" aria-label="More actions" />}
                triggerChildren={<Ellipsis />}
            />
        )
    },
}

// A short menu, such as Help, skips the search field.
export const WithoutSearch: Story = {
    render: function Render() {
        return (
            <ActionMenu
                searchable={false}
                items={[
                    { id: 'docs', label: 'Docs', onSelect: () => {} },
                    { id: 'support', label: 'Support', opensFloatingUi: true, onSelect: () => {} },
                ]}
                trigger={<Button size="icon" aria-label="Help" />}
                triggerChildren={<Ellipsis />}
            />
        )
    },
}
