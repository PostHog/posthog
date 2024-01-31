import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonRadio, LemonRadioOption, LemonRadioProps } from './LemonRadio'

type Story = StoryObj<typeof LemonRadio>
const meta: Meta<typeof LemonRadio> = {
    title: 'Lemon UI/Lemon Radio',
    component: LemonRadio,
    argTypes: {
        options: {
            control: {
                type: 'object',
            },
        },
        // Show value and onChange, but disable editing as they're handled by the template
        value: { control: { disable: true } },
        onChange: { control: { disable: true } },
    },
    args: {
        options: [
            { value: 'calendar', label: 'Calendar' },
            { value: 'calculator', label: 'Calculator' },
            { value: 'banana', label: 'Banana' },
            { value: 'settings', label: 'Settings' },
        ] as LemonRadioOption<string>[],
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonRadio> = (props: Omit<LemonRadioProps<any>, 'value' | 'onChange'>) => {
    const [value, setValue] = useState(props.options[1]?.value)

    return <LemonRadio {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Default: Story = Template.bind({})
Default.args = {}

export const FullWidth: Story = Template.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    disabledReason: '🤷‍♂️',
}
