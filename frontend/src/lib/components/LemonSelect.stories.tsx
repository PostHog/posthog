import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from './LemonSelect'

export default {
    title: 'Lemon UI/Lemon Select',
    component: LemonSelect,
    argTypes: {
        options: {
            defaultValue: {
                husky: { label: 'Husky' },
                poodle: { label: 'Poodle' },
                labrador: { label: 'Labrador' },
            },
        },
    },
} as ComponentMeta<typeof LemonSelect>

const Template: ComponentStory<typeof LemonSelect> = (props: LemonSelectProps<LemonSelectOptions>) => {
    return <LemonSelect {...props} />
}

export const Default = Template.bind({})
Default.args = {}

export const SectionedOptions = Template.bind({})
SectionedOptions.args = {
    dropdownMatchSelectWidth: false,
    options: [
        {
            label: 'Fruits',
            options: {
                orange: { label: 'Orange' },
                pineapple: { label: 'Pineapple' },
                apple: { label: 'Apple' },
            },
        },
        {
            label: 'Vegetables',
            options: {
                potato: { label: 'Potato' },
                lettuce: { label: 'Lettuce' },
            },
        },
        {
            label: (
                <div>
                    <h5>I am a Custom label!</h5>
                    <div className="text-muted mx-05 mb-05">I can put whatever I want here</div>
                </div>
            ),
            options: {
                tomato: { label: 'Tomato??' },
            },
        },
    ],
}

export const Stealth = Template.bind({})
Stealth.args = { type: 'stealth', outlined: true }

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true, value: 'poodle' }

export const LongOptions = Template.bind({})

LongOptions.args = {
    allowClear: true,
    value: '1',
    options: [...Array(100)]
        .map((_, i) => i)
        .reduce(
            (acc, x) => ({
                ...acc,
                [`${x}`]: { label: `${x}` },
            }),
            {}
        ),
}
