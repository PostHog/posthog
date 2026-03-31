import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { EditableField as EditableFieldComponent, EditableFieldProps } from './EditableField'

type Story = StoryObj<EditableFieldProps>
const meta: Meta<EditableFieldProps> = {
    title: 'Components/Editable Field',
    component: EditableFieldComponent,
    tags: ['autodocs'],
    render: (args) => {
        const [value, setValue] = useState(args.value ?? 'Lorem ipsum')

        return (
            <div className="flex">
                <EditableFieldComponent {...args} value={value} onSave={(value) => setValue(value)} />
            </div>
        )
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const MultilineWithMarkdown: Story = {
    args: {
        multiline: true,
        markdown: true,
        value: 'Lorem ipsum **dolor** sit amet, consectetur adipiscing _elit_.',
    },
}
