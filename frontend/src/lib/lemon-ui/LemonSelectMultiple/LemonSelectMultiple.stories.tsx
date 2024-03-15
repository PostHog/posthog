import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { ProfilePicture } from '../ProfilePicture'
import { LemonSelectMultiple, LemonSelectMultipleProps } from './LemonSelectMultiple'

const names = ['ben', 'marius', 'paul', 'tiina', 'tim', 'james', 'neil', 'tom', 'paul', 'thomas']

type Story = StoryObj<typeof LemonSelectMultiple>
const meta: Meta<typeof LemonSelectMultiple> = {
    title: 'Lemon UI/Lemon SelectMultiple',
    component: LemonSelectMultiple,
    args: {
        options: names.reduce(
            (acc, x, i) => ({
                ...acc,
                [`user-${i}`]: {
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
                    label: `${x} ${x}@posthog.com>`,
                },
            }),
            {}
        ),
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonSelectMultiple> = (props: LemonSelectMultipleProps) => {
    const [value, setValue] = useState(props.value || [])
    return <LemonSelectMultiple {...props} value={value} onChange={setValue} />
}

export const Default: Story = Template.bind({})
Default.args = {
    placeholder: 'Pick one email',
}

export const MultipleSelect: Story = Template.bind({})
MultipleSelect.args = {
    placeholder: 'Enter emails...',
    mode: 'multiple',
}

export const MultipleSelectWithCustom: Story = Template.bind({})
MultipleSelectWithCustom.args = {
    placeholder: 'Enter any email...',
    mode: 'multiple-custom',
}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    placeholder: 'Disabled...',
    disabled: true,
}

export const Loading: Story = Template.bind({})
Loading.args = {
    placeholder: 'Loading...',
    options: [],
    loading: true,
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const NoOptions: Story = Template.bind({})
NoOptions.args = {
    mode: 'multiple-custom',
    placeholder: 'No options...',
    options: [],
}

export const SingleOption: Story = Template.bind({})
SingleOption.args = {
    mode: 'single', // TODO: Remove single support
    placeholder: 'Only one option allowed',
}

export const PrefilledManyValues: Story = Template.bind({})
PrefilledManyValues.args = {
    mode: 'multiple-custom',
    value: names.map((_, i) => `user-${i}`),
}
