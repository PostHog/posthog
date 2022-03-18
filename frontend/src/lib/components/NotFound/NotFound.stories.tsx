import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { NotFound } from './index'

export default {
    title: 'Components/Not Found',
    component: NotFound,
} as ComponentMeta<typeof NotFound>

const Template: ComponentStory<typeof NotFound> = (args) => <NotFound {...args} />

export const NotFound_ = Template.bind({})
NotFound_.args = {
    object: 'Person',
}
