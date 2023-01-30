import { useState } from 'react'
import { ComponentMeta, ComponentStory, Story } from '@storybook/react'

import { LemonTextArea, LemonTextAreaProps, LemonTextMarkdown as _LemonTextMarkdown } from './LemonTextArea'

export default {
    title: 'Lemon UI/Lemon Text Area',
    component: LemonTextArea,
    argTypes: {
        value: {
            defaultValue:
                'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
        },
    },
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonTextArea>

const Template: ComponentStory<typeof LemonTextArea> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonTextArea {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic = Template.bind({})
Basic.args = {}

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }

export const LemonTextMarkdown: Story = () => {
    const [value, setValue] = useState('# Title\n\n**bold** _italic_')
    return <_LemonTextMarkdown value={value} onChange={(newValue) => setValue(newValue)} />
}
