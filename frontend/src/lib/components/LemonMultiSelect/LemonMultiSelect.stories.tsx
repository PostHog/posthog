import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonMultiSelect, LemonMultiSelectProps } from './LemonMultiSelect'
import { LemonSelect } from '../LemonSelect'
import { ProfilePicture } from '../ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'

export default {
    title: 'Lemon UI/Lemon MultiSelect',
    component: LemonMultiSelect,
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
} as ComponentMeta<typeof LemonMultiSelect>

const Template: ComponentStory<typeof LemonMultiSelect> = (
    props: LemonMultiSelectProps<Record<string, { label: string }>>
) => {
    const [value, setValue] = useState(props.value || [])
    return (
        <>
            <LemonSelect {...props} />
            <LemonMultiSelect {...props} value={value} onChange={setValue} />
        </>
    )
}

export const Default = Template.bind({})
Default.args = {}

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }
