import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from './LemonSelect'
import { capitalizeFirstLetter } from 'lib/utils'

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
    return (
        <div className="flex flex-row items-center w-full border p-4 gap-2">
            {(['small', undefined] as const).map((size, index) => (
                <div className="flex flex-col" key={index}>
                    <h5>size={capitalizeFirstLetter(size || 'unspecified')}</h5>
                    <LemonSelect {...props} size={size} />
                </div>
            ))}
        </div>
    )
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
                    <div className="text-muted mx-2 mb-2">I can put whatever I want here</div>
                </div>
            ),
            options: {
                tomato: { label: 'Tomato??' },
            },
        },
    ],
}

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
