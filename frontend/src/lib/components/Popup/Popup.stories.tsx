import { ComponentStory, ComponentMeta } from '@storybook/react'

import { Popup } from './Popup'
import { IconArrowDropDown } from '../icons'

export default {
    title: 'Lemon UI/Popup',
    component: Popup,
} as ComponentMeta<typeof Popup>

const Template: ComponentStory<typeof Popup> = (args) => <Popup {...args} />

export const Popup_ = Template.bind({})
Popup_.args = {
    visible: true,
    children: (
        <span className="text-2xl">
            <IconArrowDropDown />
        </span>
    ),
    overlay: (
        <>
            <h3>Surprise! 😱</h3>
            <span>You have been gnomed.</span>
        </>
    ),
}
