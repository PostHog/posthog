import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonMultiSelect, LemonMultiSelectProps } from './LemonMultiSelect'
import { LemonSelect } from '../LemonSelect'
import { ProfilePicture } from '../ProfilePicture'

export default {
    title: 'Lemon UI/Lemon MultiSelect',
    component: LemonMultiSelect,
    argTypes: {
        options: {
            defaultValue: {
                'ben@posthog.com': {
                    label: (
                        <span>
                            Ben <b>{'<ben@posthog.com>'}</b>
                        </span>
                    ),
                    icon: <ProfilePicture name={'ben'} email={'ben@posthog.com'} size="sm" />,
                },
                'paul@posthog.com': {
                    label: (
                        <span>
                            Paul <b>{'<paul@posthog.com>'}</b>
                        </span>
                    ),
                    icon: <ProfilePicture name={'paul'} email={'paul@posthog.com'} size="sm" />,
                },
                'marius@posthog.com': {
                    label: (
                        <span>
                            Marius <b>{'<marius@posthog.com>'}</b>
                        </span>
                    ),
                    icon: <ProfilePicture name={'marius'} email={'marius@posthog.com'} size="sm" />,
                },
            },
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
Default.args = {
    type: 'secondary',
}

export const Stealth = Template.bind({})
Stealth.args = { type: 'stealth', outlined: true }

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true, value: ['poodle'] }
