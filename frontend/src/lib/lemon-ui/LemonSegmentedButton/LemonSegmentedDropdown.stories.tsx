import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconBook, IconCalculator, IconCalendar, IconGear, IconHome, IconMagicWand } from '@posthog/icons'

import { LemonSegmentedButtonOption } from './LemonSegmentedButton'
import { LemonSegmentedDropdown, LemonSegmentedDropdownProps } from './LemonSegmentedDropdown'

type Story = StoryObj<typeof LemonSegmentedDropdown>
const meta: Meta<typeof LemonSegmentedDropdown> = {
    title: 'Lemon UI/Lemon Segmented Dropdown',
    component: LemonSegmentedDropdown,
    argTypes: {
        options: {
            control: {
                type: 'object',
            },
        },
        splitIndex: {
            control: {
                type: 'number',
            },
        },
        value: { control: { disable: true } },
        onChange: { control: { disable: true } },
    },
    args: {
        options: [
            { value: 'calendar', label: 'Calendar', icon: <IconCalendar /> },
            { value: 'calculator', label: 'Calculator', icon: <IconCalculator /> },
            { value: 'home', label: 'Home', icon: <IconHome /> },
            { value: 'magic', label: 'Magic', icon: <IconMagicWand /> },
            { value: 'book', label: 'Book', icon: <IconBook /> },
            { value: 'settings', label: 'Settings', icon: <IconGear /> },
        ] as LemonSegmentedButtonOption<string>[],
        splitIndex: 2,
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonSegmentedDropdown> = (
    props: Omit<LemonSegmentedDropdownProps<any>, 'value' | 'onChange'>
) => {
    const [value, setValue] = useState(props.options[0]?.value)

    return <LemonSegmentedDropdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Default: Story = Template.bind({})
Default.args = {}

export const SplitAt3: Story = Template.bind({})
SplitAt3.args = {
    splitIndex: 3,
}

export const FullWidth: Story = Template.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const Small: Story = Template.bind({})
Small.args = {
    size: 'small',
}

const TemplateWithDropdownSelected: StoryFn<typeof LemonSegmentedDropdown> = (
    props: Omit<LemonSegmentedDropdownProps<any>, 'value' | 'onChange'>
) => {
    const splitIndex = props.splitIndex ?? props.options.length
    const [value, setValue] = useState(props.options[splitIndex]?.value)

    return <LemonSegmentedDropdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const DropdownSelectedByDefault: Story = TemplateWithDropdownSelected.bind({})
DropdownSelectedByDefault.args = {
    options: [
        { value: 'calendar', label: 'Calendar', icon: <IconCalendar /> },
        { value: 'calculator', label: 'Calculator', icon: <IconCalculator /> },
        { value: 'home', label: 'Home', icon: <IconHome /> },
        { value: 'magic', label: 'Magic', icon: <IconMagicWand /> },
        { value: 'book', label: 'Book', icon: <IconBook /> },
        { value: 'settings', label: 'Settings', icon: <IconGear /> },
    ] as LemonSegmentedButtonOption<string>[],
    splitIndex: 2,
}
DropdownSelectedByDefault.parameters = {
    docs: {
        storyDescription: 'When an option in the dropdown is selected, it displays that option.',
    },
}
