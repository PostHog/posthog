import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { LemonPopover } from '.'
import { Button } from 'antd'

export default {
    title: 'PostHog/Components/LemonPopover',
    component: LemonPopover,
    parameters: { options: { showPanel: true } },
} as ComponentMeta<typeof LemonPopover>

const Template: ComponentStory<typeof LemonPopover> = (args) => <LemonPopover {...args} />

export const Surprise = Template.bind({})
Surprise.args = {
    children: <Button type="primary">Click here…</Button>,
    content: (
        <>
            <h3>Surprise! 😱</h3>You have been gnomed.
        </>
    ),
    placement: 'bottom-left',
}
