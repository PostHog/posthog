import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { ProfilePicture } from '../ProfilePicture'
import { LemonSelectMultiple, LemonSelectMultipleProps } from './LemonSelectMultiple'

const names = ['ben', 'marius', 'paul', 'tiina', 'tim', 'james', 'neil', 'tom', 'annika', 'thomas']

type Story = StoryObj<typeof LemonSelectMultiple>
const meta: Meta<typeof LemonSelectMultiple> = {
    title: 'Lemon UI/Lemon SelectMultiple',
    component: LemonSelectMultiple,
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
            label: `${x} ${x}@posthog.com>`,
        })),
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonSelectMultiple> = (props: LemonSelectMultipleProps) => {
    const [value, setValue] = useState(props.value || [])
    return <LemonSelectMultiple {...props} value={value} onChange={setValue} mode="single" />
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
    mode: 'multiple',
    allowCustomValues: true,
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
    mode: 'multiple',
    allowCustomValues: true,
    placeholder: 'No options...',
    options: [],
}

export const SingleOption: Story = Template.bind({})
SingleOption.args = {
    mode: 'single',
    placeholder: 'Only one option allowed',
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
