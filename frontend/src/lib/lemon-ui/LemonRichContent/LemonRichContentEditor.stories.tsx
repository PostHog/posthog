import type { Meta, StoryObj } from '@storybook/react'

import { LemonRichContentEditor, LemonRichContentEditorProps } from './LemonRichContentEditor'

type Story = StoryObj<LemonRichContentEditorProps>
const meta: Meta<LemonRichContentEditorProps> = {
    title: 'Lemon UI/Lemon Rich Content Editor',
    component: LemonRichContentEditor,
    tags: ['autodocs'],
}

export default meta

export const EmptyLemonRichContentEditor: Story = {
    args: { initialContent: undefined },
}
