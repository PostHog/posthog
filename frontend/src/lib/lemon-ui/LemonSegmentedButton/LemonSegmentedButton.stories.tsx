import { ComponentMeta, ComponentStory } from '@storybook/react'
import { useState } from 'react'
import { IconCalculate, IconCalendar, IconLightBulb, IconSettings } from '../icons'
import { LemonSegmentedButton, LemonSegmentedButtonOption, LemonSegmentedButtonProps } from './LemonSegmentedButton'

export default {
    title: 'Lemon UI/Lemon Segmented Button',
    component: LemonSegmentedButton,
    argTypes: {
        options: {
            control: {
                type: 'object',
            },
            defaultValue: [
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
        // Show value and onChange, but disable editing as they're handled by the template
        value: { control: { disable: true } },
        onChange: { control: { disable: true } },
    },
} as ComponentMeta<typeof LemonSegmentedButton>

const Template: ComponentStory<typeof LemonSegmentedButton> = (
    props: Omit<LemonSegmentedButtonProps<any>, 'value' | 'onChange'>
) => {
    const [value, setValue] = useState(props.options[1]?.value)

    return <LemonSegmentedButton {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const _LemonSegmentedButton = Template.bind({})
_LemonSegmentedButton.args = {}
