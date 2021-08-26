import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { NotFound } from './index'

export default {
    title: 'PostHog/Components/NotFound',
    component: NotFound,
} as ComponentMeta<typeof NotFound>

const Template: ComponentStory<typeof NotFound> = (args) => <NotFound {...args} />

export const Person = Template.bind({})
Person.args = {
    object: 'Person',
}
