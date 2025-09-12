import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { JSONContent } from '@tiptap/core'
import { useState } from 'react'

import { LemonRichTextEditor, LemonRichTextEditorProps } from './LemonRichTextEditor'

type Story = StoryObj<typeof LemonRichTextEditor>
const meta: Meta<typeof LemonRichTextEditor> = {
    title: 'Lemon UI/Lemon Rich Text Editor',
    component: LemonRichTextEditor,
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonRichTextEditor> = (props: LemonRichTextEditorProps) => {
    const [value, setValue] = useState<JSONContent | undefined>(props.initialContent)
    return <LemonRichTextEditor {...props} content={value} onChange={(newValue) => setValue(newValue)} />
}

export const EmptyLemonRichTextEditor: Story = Template.bind({})
EmptyLemonRichTextEditor.args = { content: undefined }
