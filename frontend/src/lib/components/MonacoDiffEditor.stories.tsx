import { StoryObj } from '@storybook/react'
import { Meta } from '@storybook/react'

import MonacoDiffEditor, { MonacoDiffEditorProps } from './MonacoDiffEditor'

type Story = StoryObj<MonacoDiffEditorProps>
const meta: Meta<MonacoDiffEditorProps> = {
    title: 'Components/Monaco Diff Editor',
    component: MonacoDiffEditor as any,
    tags: ['autodocs', 'test-skip'], // There are too many icons, the snapshots are huge in table form
}
export default meta

export const Default: Story = {
    args: {
        original: 'console.log("Hello, world!");',
        modified: 'console.log("Hello, world!", "foo");',
    },
}

export const JSONDiff: Story = {
    args: {
        original: JSON.stringify({ a: 1, b: 2 }),
        modified: JSON.stringify({ a: 1, b: 3 }),
    },
}
