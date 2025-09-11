import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { IconBook, IconCalculator, IconCalendar, IconGear } from '@posthog/icons'

import { LemonSegmentedSelect, LemonSegmentedSelectProps } from './LemonSegmentedSelect'

type Story = StoryObj<typeof LemonSegmentedSelect>
const meta: Meta<typeof LemonSegmentedSelect> = {
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
}
export default meta

const Template: StoryFn<typeof LemonSegmentedSelect> = (props: Omit<LemonSegmentedSelectProps<any>, 'value'>) => {
    return <LemonSegmentedSelect {...props} value={props.options[1]?.value} />
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
