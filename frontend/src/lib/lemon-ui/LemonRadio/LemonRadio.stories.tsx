import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonRadio, LemonRadioOption, LemonRadioProps } from './LemonRadio'

type Story = StoryObj<LemonRadioProps<string>>
const meta: Meta<LemonRadioProps<string>> = {
    title: 'Lemon UI/Lemon Radio',
    component: LemonRadio as any,
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
            { value: 'banana', label: 'Banana', disabledReason: 'Bananas are not allowed on pizza' },
            { value: 'settings', label: 'Settings' },
        ] as LemonRadioOption<string>[],
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.options[1]?.value)

        return <LemonRadio {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const WithDescriptions: Story = {
    args: {
        options: [
            { value: 'calendar', label: 'Calendar' },
            { value: 'calculator', label: 'Calculator', description: '2.1 + 2.01 = 4.109999999999999' },
            {
                value: 'banana',
                label: 'Banana',
                disabledReason: 'Bananas are not allowed on pizza',
                description:
                    'Note: The banana addon ships from Costa Rica, which will add 2 working days of a delay to your order.',
            },
        ],
    },
}

export const WithTopPosition: Story = {
    args: {
        radioPosition: 'top',
    },
}
