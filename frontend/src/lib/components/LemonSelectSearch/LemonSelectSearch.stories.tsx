import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSelectSearch, LemonSelectSearchProps } from './LemonSelectSearch'
import { ProfilePicture } from '../ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon MultiSelect',
    component: LemonSelectSearch,
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
} as ComponentMeta<typeof LemonSelectSearch>

const Template: ComponentStory<typeof LemonSelectSearch> = (
    props: LemonSelectSearchProps<Record<string, { label: string }>>
) => {
    const [value, setValue] = useState(props.value || [])
    return (
        <>
            <LemonSelectSearch {...props} value={value} onChange={setValue} />
        </>
    )
}

export const Default = Template.bind({})
Default.args = {
    placeholder: 'Pick one emails',
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
Disabled.args = { disabled: true }
