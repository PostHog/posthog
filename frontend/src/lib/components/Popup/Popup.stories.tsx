import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { Popup } from './Popup'
import { Button } from 'antd'

export default {
    title: 'Lemon UI/Popup',
    component: Popup,
} as ComponentMeta<typeof Popup>

const Template: ComponentStory<typeof Popup> = (args) => <Popup {...args} />

export const Surprise = Template.bind({})
Surprise.args = {
    visible: true,
    children: <Button type="primary">Click here…</Button>,
    overlay: (
        <>
            <h3>Surprise! 😱</h3>You have been gnomed.
        </>
    ),
    placement: 'bottom-start',
}
