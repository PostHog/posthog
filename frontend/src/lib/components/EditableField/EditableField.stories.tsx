import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { EditableField as EditableFieldComponent } from './EditableField'

const meta: Meta<typeof EditableFieldComponent> = {
    title: 'Components/Editable Field',
    component: EditableFieldComponent,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof EditableFieldComponent> = (args) => {
    const [value, setValue] = useState(args.value ?? 'Lorem ipsum')

    return (
        <div className="flex">
            <EditableFieldComponent {...args} value={value} onSave={(value) => setValue(value)} />
        </div>
    )
}

export const Default = Template.bind({})

export const MultilineWithMarkdown = Template.bind({})
MultilineWithMarkdown.args = {
    multiline: true,
    markdown: true,
    value: 'Lorem ipsum **dolor** sit amet, consectetur adipiscing _elit_.',
}
