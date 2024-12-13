import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { ProfilePicture } from '../ProfilePicture'
import { LemonInputSelect, LemonInputSelectProps } from './LemonInputSelect'

const names = [
    'ben',
    'marius',
    'paul',
    'tiina',
    'tim',
    'james',
    'neil',
    'tom',
    'annika',
    'thomas',
    'eric',
    'yakko',
    'manoel',
    'leon',
    'lottie',
    'charles',
]

type Story = StoryObj<typeof LemonInputSelect>
const meta: Meta<typeof LemonInputSelect> = {
    title: 'Lemon UI/Lemon Input Select',
    component: LemonInputSelect,
    args: {
        options: names.map((x, i) => ({
            key: `user-${i}`,
            labelComponent: (
                <span className="flex gap-2 items-center">
                    <ProfilePicture
                        user={{
                            first_name: x,
                            email: `${x}@posthog.com`,
                        }}
                        size="sm"
                    />
                    <span>
                        {capitalizeFirstLetter(x)} <b>{`<${x}@posthog.com>`}</b>
                    </span>
                </span>
            ),
            label: `${capitalizeFirstLetter(x)} <${x}@posthog.com>`,
        })),
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonInputSelect> = (props: LemonInputSelectProps) => {
    const [value, setValue] = useState(props.value || [])
    return <LemonInputSelect {...props} value={value} onChange={setValue} className="w-140" />
}

export const Default: Story = Template.bind({})
Default.args = {
    placeholder: 'Pick one email',
    mode: 'single',
}

export const MultipleSelect: Story = Template.bind({})
MultipleSelect.args = {
    placeholder: 'Pick email addresses',
    mode: 'multiple',
}

export const MultipleSelectWithCustom: Story = Template.bind({})
MultipleSelectWithCustom.args = {
    placeholder: 'Enter URLs',
    mode: 'multiple',
    allowCustomValues: true,
    options: [
        {
            key: 'http://posthog.com/docs',
            label: 'http://posthog.com/docs',
        },
        {
            key: 'http://posthog.com/pricing',
            label: 'http://posthog.com/pricing',
        },

        {
            key: 'http://posthog.com/products',
            label: 'http://posthog.com/products',
        },
    ],
}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    mode: 'single',
    placeholder: 'Disabled...',
    disabled: true,
}

export const Loading: Story = Template.bind({})
Loading.args = {
    mode: 'single',
    placeholder: 'Loading with options...',
    loading: true,
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const EmptyLoading: Story = Template.bind({})
EmptyLoading.args = {
    mode: 'single',
    placeholder: 'Loading without options...',
    options: [],
    loading: true,
}
EmptyLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const NoOptions: Story = Template.bind({})
NoOptions.args = {
    mode: 'multiple',
    allowCustomValues: true,
    placeholder: 'No options...',
    options: [],
}

export const SingleOptionWithCustom: Story = Template.bind({})
SingleOptionWithCustom.args = {
    mode: 'single',
    allowCustomValues: true,
    placeholder: 'Only one option allowed but can be custom',
}

export const PrefilledManyValues: Story = Template.bind({})
PrefilledManyValues.args = {
    mode: 'multiple',
    allowCustomValues: true,
    value: names.map((_, i) => `user-${i}`),
}
