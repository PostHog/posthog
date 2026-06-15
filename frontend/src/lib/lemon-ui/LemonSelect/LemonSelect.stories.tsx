import type { Meta, StoryObj } from '@storybook/react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { capitalizeFirstLetter } from 'lib/utils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LemonSelect, LemonSelectOptions, LemonSelectProps } from './LemonSelect'

type Story = StoryObj<LemonSelectProps<any>>
const meta: Meta<LemonSelectProps<any>> = {
    title: 'Lemon UI/Lemon Select',
    component: LemonSelect as any,
    args: {
        options: [
            { value: 'husky', label: 'Husky' },
            { value: 'poodle', label: 'Poodle' },
            { value: 'labrador', label: 'Labrador' },
        ] as LemonSelectOptions<string>,
    },
    tags: ['autodocs'],
    render: (props) => {
        return (
            <div className="flex flex-row items-center w-full border p-4 gap-2">
                {(['small', 'medium', 'large', undefined] as const).map((size, index) => (
                    <div className="flex flex-col" key={index}>
                        <h5>size={capitalizeFirstLetter(size || 'unspecified')}</h5>
                        <LemonSelect {...props} size={size} />
                    </div>
                ))}
            </div>
        )
    },
}
export default meta

export const Flat: Story = {
    args: {},
}

export const SectionedOptions: Story = {
    args: {
        dropdownMatchSelectWidth: false,
        options: [
            {
                title: 'Fruits',
                options: [
                    { value: 'orange', label: 'Orange' },
                    { value: 'pineapple', label: 'Pineapple' },
                    { value: 'apple', label: 'Apple' },
                ],
            },
            {
                title: 'Vegetables',
                options: [
                    { value: 'potato', label: 'Potato' },
                    { value: 'lettuce', label: 'Lettuce' },
                ],
            },
            {
                title: (
                    <div>
                        <h5>I am a Custom label!</h5>
                        <div className="text-secondary mx-2 mb-2">I can put whatever I want here</div>
                    </div>
                ),
                options: [{ value: 'tomato', label: 'Tomato??', disabled: true }],
                footer: (
                    <div className="bg-primary rounded p-2">
                        <p className="text-secondary max-w-60">
                            I am a custom footer! <br />
                            This might be a good time to tell you about our premium features...
                        </p>
                    </div>
                ),
            },
        ] as LemonSelectOptions<string>,
    },
}

export const MixedValuesTypes: Story = {
    args: {
        dropdownMatchSelectWidth: false,
        options: [
            { value: 'orange', label: 'Orange' },
            { value: 2, label: 'Pineapple - 2' },
            { value: 'apple', label: 'Apple' },
            { value: '4', label: 'Potato - string 4' },
            { value: 'lettuce', label: 'Lettuce' },
            { value: 6, label: 'Tomato - 6' },
        ] as LemonSelectOptions<string | number>,
    },
}

export const NestedSelect: Story = {
    args: {
        dropdownMatchSelectWidth: false,
        options: [
            { label: 'Capybara', value: 'capybara' },
            {
                label: 'Elephant',
                options: [
                    { label: 'African elephant', value: 'elephant-african' },
                    { label: 'Asian elephant', value: 'elephant-asian' },
                ],
            },
        ] as LemonSelectOptions<string | number>,
    },
}

export const Clearable: Story = {
    args: { allowClear: true, value: 'poodle' },
}

export const LongOptions: Story = {
    args: {
        allowClear: true,
        value: '1',
        options: [...Array(100)].map((_, x) => ({ value: `${x}`, label: `${x}` })),
    },
}

export const CustomElement: Story = {
    args: {
        value: 1,
        options: [
            {
                value: 1,
                labelInMenu: <i>Wow (Surprised)</i>,
                label: 'Wow',
            },
            {
                value: 2,
                labelInMenu: <i>Ohh (Blushing)</i>,
                label: 'Ohh',
            },
        ],
    },
}

export const FullWidth: Story = {
    render: (props: LemonSelectProps<any>) => {
        return (
            <div className="items-center w-full border p-4 gap-2">
                <LemonSelect {...props} fullWidth={true} allowClear={true} value="poodle" />
            </div>
        )
    },
}

export const WithAccessControl: Story = {
    render: () => {
        const options = [
            { value: 'husky', label: 'Husky' },
            { value: 'poodle', label: 'Poodle' },
            { value: 'labrador', label: 'Labrador' },
        ] as LemonSelectOptions<string>

        return (
            <div className="flex gap-4 items-center">
                <AccessControlAction
                    resourceType={AccessControlResourceType.Dashboard}
                    minAccessLevel={AccessControlLevel.Viewer}
                    userAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonSelect options={options} placeholder="Enabled (editor ≥ viewer)" />
                </AccessControlAction>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Dashboard}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={AccessControlLevel.Viewer}
                >
                    <LemonSelect options={options} placeholder="Disabled (viewer < editor)" />
                </AccessControlAction>
            </div>
        )
    },
}
