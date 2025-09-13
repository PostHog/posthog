import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonRichContentEditor, LemonRichContentEditorProps } from './LemonRichContentEditor'

type Story = StoryObj<typeof LemonRichContentEditor>
const meta: Meta<typeof LemonRichContentEditor> = {
    title: 'Lemon UI/Lemon Rich Content Editor',
    component: LemonRichContentEditor,
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonRichContentEditor> = (props: LemonRichContentEditorProps) => {
    return <LemonRichContentEditor {...props} />
}

export const EmptyLemonRichContentEditor: Story = Template.bind({})
EmptyLemonRichContentEditor.args = { initialContent: undefined }
