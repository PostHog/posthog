import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelect, LemonSelectProps } from './LemonSelect'

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

const Template: ComponentStory<typeof LemonSelect> = (props: LemonSelectProps<Record<string, { label: string }>>) => {
    return <LemonSelect {...props} />
}

export const Default = Template.bind({})
Default.args = {}

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
