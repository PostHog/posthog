import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonTextArea, LemonTextAreaMarkdown as _LemonTextMarkdown, LemonTextAreaProps } from './LemonTextArea'

type Story = StoryObj<typeof LemonTextArea>
const meta: Meta<typeof LemonTextArea> = {
    title: 'Lemon UI/Lemon Text Area',
    component: LemonTextArea,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonTextArea> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonTextArea {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic: Story = Template.bind({})
Basic.args = {}

export const Disabled: Story = Template.bind({})
Disabled.args = { disabled: true }

export const LemonTextMarkdown = (): JSX.Element => {
    const [value, setValue] = useState('# Title\n\n**bold** _italic_')
    return <_LemonTextMarkdown value={value} onChange={(newValue) => setValue(newValue)} />
}
