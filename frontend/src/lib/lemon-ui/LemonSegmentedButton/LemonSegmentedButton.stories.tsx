import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconBook, IconCalculator, IconCalendar, IconGear } from '@posthog/icons'

import { LemonSegmentedButton, LemonSegmentedButtonOption, LemonSegmentedButtonProps } from './LemonSegmentedButton'

type Story = StoryObj<LemonSegmentedButtonProps<string>>
const meta: Meta<LemonSegmentedButtonProps<string>> = {
    title: 'Lemon UI/Lemon Segmented Button',
    component: LemonSegmentedButton as any,
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
            { value: 'calculator', label: 'Calculator', icon: <IconCalculator /> },
            {
                value: 'banana',
                label: 'Banana',
                icon: <IconBook />,
                disabledReason: 'Bananas are not allowed on these premises.',
            },
            { value: 'settings', label: 'Settings', icon: <IconGear /> },
        ] as LemonSegmentedButtonOption<string>[],
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.options[1]?.value)

        return <LemonSegmentedButton {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const FullWidth: Story = {
    args: {
        fullWidth: true,
    },
}

export const Small: Story = {
    args: {
        size: 'small',
    },
}

export const Disabled: Story = {
    args: {
        disabledReason: 'Choose a chart type first.',
    },
}
