import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelectMultiple, LemonSelectMultipleProps } from './LemonSelectMultiple'
import { ProfilePicture } from '../ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon SelectMultiple',
    component: LemonSelectMultiple,
    argTypes: {
        options: {
            defaultValue: ['ben', 'marius', 'paul', 'tiina', 'li'].reduce(
                (acc, x) => ({
                    ...acc,
                    [`${x}@posthog.com`]: {
                        label: (
                            <span className="flex gap-05 items-center">
                                <ProfilePicture name={x} email={`${x}@posthog.com`} size="sm" />
                                <span>
                                    {capitalizeFirstLetter(x)} <b>{`<${x}@posthog.com>`}</b>
                                </span>
                            </span>
                        ),
                    },
                }),
                {}
            ),
        },
    },
} as ComponentMeta<typeof LemonSelectMultiple>

const Template: ComponentStory<typeof LemonSelectMultiple> = (props: LemonSelectMultipleProps) => {
    const [value, setValue] = useState(props.value || [])
    return <LemonSelectMultiple {...props} value={value} onChange={setValue} />
}

export const Default = Template.bind({})
Default.args = {
    placeholder: 'Pick one email',
}

export const MultipleSelect = Template.bind({})
MultipleSelect.args = {
    placeholder: 'Enter emails...',
    mode: 'multiple',
}

export const MultipleSelectWithCustom = Template.bind({})
MultipleSelectWithCustom.args = {
    placeholder: 'Enter any email...',
    mode: 'multiple-custom',
}

export const Disabled = Template.bind({})
Disabled.args = {
    placeholder: 'Disabled...',
    disabled: true,
}

export const Loading = Template.bind({})
Loading.args = {
    placeholder: 'Loading...',
    options: [],
    loading: true,
}

export const NoOptions = Template.bind({})
NoOptions.args = {
    mode: 'multiple-custom',
    placeholder: 'No options...',
    options: [],
}
