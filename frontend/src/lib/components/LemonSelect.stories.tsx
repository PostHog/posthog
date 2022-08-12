import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from './LemonSelect'
import { capitalizeFirstLetter } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon Select',
    component: LemonSelect,
    argTypes: {
        options: {
            defaultValue: [
                { key: 'husky', label: 'Husky' },
                { key: 'poodle', label: 'Poodle' },
                { key: 'labrador', label: 'Labrador' },
            ] as LemonSelectOptions<string>,
        },
    },
} as ComponentMeta<typeof LemonSelect>

const Template: ComponentStory<typeof LemonSelect> = (props: LemonSelectProps<string>) => {
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
            title: 'Fruits',
            options: [
                { key: 'orange', label: 'Orange' },
                { key: 'pineapple', label: 'Pineapple' },
                { key: 'apple', label: 'Apple' },
            ],
        },
        {
            title: 'Vegetables',
            options: [
                { key: 'potato', label: 'Potato' },
                { key: 'lettuce', label: 'Lettuce' },
            ],
        },
        {
            title: (
                <div>
                    <h5>I am a Custom label!</h5>
                    <div className="text-muted mx-2 mb-2">I can put whatever I want here</div>
                </div>
            ),
            options: [{ key: 'tomato', label: 'Tomato??' }],
        },
    ] as LemonSelectOptions<string>,
}

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true, value: 'poodle' }

export const LongOptions = Template.bind({})

LongOptions.args = {
    allowClear: true,
    value: '1',
    options: [...Array(100)].map((_, x) => ({ key: `${x}`, label: `${x}` })),
}
