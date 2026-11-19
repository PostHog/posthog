import type { Meta, StoryObj } from '@storybook/react'
import { DownloadIcon, XIcon } from 'lucide-react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { Separator } from './separator'
import { Text } from './text'

const meta = {
    title: 'Primitives/Inverted surface',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

function SelectionBar(): React.ReactElement {
    return (
        <div data-quill-inverted className="flex items-center gap-2 rounded-lg bg-background px-3 py-2 text-foreground">
            <Checkbox checked aria-label="Select all" />
            <Text size="sm" weight="medium">
                3 tables selected
            </Text>
            <Text size="sm" variant="muted">
                of 42
            </Text>
            <Separator orientation="vertical" className="mx-1 h-5" />
            <Button variant="outline">
                <DownloadIcon />
                Export
            </Button>
            <Button>Add tag</Button>
            <Button variant="primary">Certify</Button>
            <Button variant="link">Learn more</Button>
            <Button size="icon" variant="outline" aria-label="Clear selection">
                <XIcon />
            </Button>
        </div>
    )
}

function Page({ mode }: { mode: 'light' | 'dark' }): React.ReactElement {
    return (
        <div className={mode === 'dark' ? 'dark' : undefined}>
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-background p-6 text-foreground">
                <Text size="sm" variant="muted">
                    {mode === 'dark' ? 'Dark page' : 'Page in the current theme'}
                </Text>
                <SelectionBar />
            </div>
        </div>
    )
}

export const SelectionBarInBothModes: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            <Page mode="light" />
            <Page mode="dark" />
        </div>
    ),
}
