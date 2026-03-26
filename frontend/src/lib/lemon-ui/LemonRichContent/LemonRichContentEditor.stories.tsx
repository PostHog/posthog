import type { Meta, StoryObj } from '@storybook/react'

import { LemonRichContentEditor } from './LemonRichContentEditor'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof LemonRichContentEditor> = {
    title: 'Lemon UI/Lemon Rich Content Editor',
    component: LemonRichContentEditor,
    tags: ['autodocs'],
}

export default meta

export const EmptyLemonRichContentEditor: Story = {
    args: { initialContent: undefined },
}
