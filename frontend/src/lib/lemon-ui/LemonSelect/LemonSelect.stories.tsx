import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from './LemonSelect'
import { capitalizeFirstLetter } from 'lib/utils'
import { SurprisedHog, BlushingHog } from 'lib/components/hedgehogs'

export default {
    title: 'Lemon UI/Lemon Select',
    component: LemonSelect,
    argTypes: {
        options: {
            defaultValue: [
                { value: 'husky', label: 'Husky' },
                { value: 'poodle', label: 'Poodle' },
                { value: 'labrador', label: 'Labrador' },
            ] as LemonSelectOptions<string>,
        },
    },
} as ComponentMeta<typeof LemonSelect>

const Template: ComponentStory<typeof LemonSelect> = (props: LemonSelectProps<any>) => {
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
                    <div className="text-muted mx-2 mb-2">I can put whatever I want here</div>
                </div>
            ),
            options: [{ value: 'tomato', label: 'Tomato??', disabled: true }],
            footer: (
                <div className="bg-side rounded p-2">
                    <p className="text-muted" style={{ maxWidth: '15rem' }}>
                        I am a custom footer! <br />
                        This might be a good time to tell you about our premium features...
                    </p>
                </div>
            ),
        },
    ] as LemonSelectOptions<string>,
}

export const MixedValuesTypes = Template.bind({})
MixedValuesTypes.args = {
    dropdownMatchSelectWidth: false,
    options: [
        { value: 'orange', label: 'Orange' },
        { value: 2, label: 'Pineapple - 2' },
        { value: 'apple', label: 'Apple' },
        { value: '4', label: 'Potato - string 4' },
        { value: 'lettuce', label: 'Lettuce' },
        { value: 6, label: 'Tomato - 6' },
    ] as LemonSelectOptions<string | number>,
}

export const NestedSelect = Template.bind({})
NestedSelect.args = {
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
}

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true, value: 'poodle' }

export const LongOptions = Template.bind({})
LongOptions.args = {
    allowClear: true,
    value: '1',
    options: [...Array(100)].map((_, x) => ({ value: `${x}`, label: `${x}` })),
}

export const CustomElement = Template.bind({})
CustomElement.args = {
    value: 1,
    options: [
        {
            value: 1,
            element: (
                <div>
                    <SurprisedHog className="w-10 h-10 mr-4" />
                    Surprised
                </div>
            ),
            label: 'Wow',
        },
        {
            value: 2,
            element: (
                <div>
                    <BlushingHog className="w-10 h-10 mr-4" />
                    Blushing
                </div>
            ),
            label: 'Ohh',
        },
    ],
}

export const FullWidth: ComponentStory<typeof LemonSelect> = (props: LemonSelectProps<any>) => {
    return (
        <div className="items-center w-full border p-4 gap-2">
            <LemonSelect {...props} fullWidth={true} allowClear={true} value={'poodle'} />
        </div>
    )
}
