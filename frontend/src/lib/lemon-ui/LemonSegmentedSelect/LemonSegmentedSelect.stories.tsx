import type { Meta, StoryObj } from '@storybook/react'

import { IconBook, IconCalculator, IconCalendar, IconGear } from '@posthog/icons'

import { LemonSegmentedSelect, LemonSegmentedSelectProps } from './LemonSegmentedSelect'

type Story = StoryObj<LemonSegmentedSelectProps<string>>
const meta: Meta<LemonSegmentedSelectProps<string>> = {
    title: 'Lemon UI/Lemon Segmented Select',
    component: LemonSegmentedSelect,
    argTypes: {
        options: {
            control: {
                type: 'object',
            },
        },
        shrinkOn: { control: { type: 'number' } },
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
        ],
    },
    tags: ['autodocs'],
    render: (props) => {
        return <LemonSegmentedSelect {...props} value={props.options[1]?.value} />
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
