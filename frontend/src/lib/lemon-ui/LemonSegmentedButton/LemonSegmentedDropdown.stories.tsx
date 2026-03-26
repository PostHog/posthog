import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconBook, IconCalculator, IconCalendar, IconGear, IconHome, IconMagicWand } from '@posthog/icons'

import { LemonSegmentedButtonOption } from './LemonSegmentedButton'
import { LemonSegmentedDropdown, LemonSegmentedDropdownProps } from './LemonSegmentedDropdown'

type Story = StoryObj<typeof meta>
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
    render: (props: Omit<LemonSegmentedDropdownProps<any>, 'value' | 'onChange'>) => {
        const [value, setValue] = useState(props.options[0]?.value)

        return <LemonSegmentedDropdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const SplitAt3: Story = {
    args: {
        splitIndex: 3,
    },
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

export const DropdownSelectedByDefault: Story = {
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
    parameters: {
        docs: {
            storyDescription: 'When an option in the dropdown is selected, it displays that option.',
        },
    },
    render: (props: Omit<LemonSegmentedDropdownProps<any>, 'value' | 'onChange'>) => {
        const splitIndex = props.splitIndex ?? props.options.length
        const [value, setValue] = useState(props.options[splitIndex]?.value)

        return <LemonSegmentedDropdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}
