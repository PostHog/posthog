import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { JSONContent } from '@tiptap/core'
import { useState } from 'react'

import { LemonRichContentEditor, LemonRichContentEditorProps } from './LemonRichContentEditor'

type Story = StoryObj<typeof LemonRichContentEditor>
const meta: Meta<typeof LemonRichContentEditor> = {
    title: 'Lemon UI/Lemon Rich Content Editor',
    component: LemonRichContentEditor,
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonRichContentEditor> = (props: LemonRichContentEditorProps) => {
    const [value, setValue] = useState<JSONContent | undefined>(props.initialContent)
    return <LemonRichContentEditor {...props} content={value} onChange={(newValue) => setValue(newValue)} />
}

export const EmptyLemonRichContentEditor: Story = Template.bind({})
EmptyLemonRichContentEditor.args = { content: undefined }
