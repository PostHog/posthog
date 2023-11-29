import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconCalculate, IconCalendar, IconLightBulb, IconSettings } from '../icons'
import { LemonSegmentedButton, LemonSegmentedButtonOption, LemonSegmentedButtonProps } from './LemonSegmentedButton'

type Story = StoryObj<typeof LemonSegmentedButton>
const meta: Meta<typeof LemonSegmentedButton> = {
    title: 'Lemon UI/Lemon Segmented Button',
    component: LemonSegmentedButton,
    parameters: {
        testOptions: {
            include3000: true,
        },
    },
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
            { value: 'calendar', label: 'Calendar', icon: <IconCalendar /> },
            { value: 'calculator', label: 'Calculator', icon: <IconCalculate /> },
            {
                value: 'banana',
                label: 'Banana',
                icon: <IconLightBulb />,
                disabledReason: 'Bananas are not allowed on these premises.',
            },
            { value: 'settings', label: 'Settings', icon: <IconSettings /> },
        ] as LemonSegmentedButtonOption<string>[],
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonSegmentedButton> = (
    props: Omit<LemonSegmentedButtonProps<any>, 'value' | 'onChange'>
) => {
    const [value, setValue] = useState(props.options[1]?.value)

    return <LemonSegmentedButton {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Default: Story = Template.bind({})
Default.args = {}

export const FullWidth: Story = Template.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const Small: Story = Template.bind({})
Small.args = {
    size: 'small',
}
