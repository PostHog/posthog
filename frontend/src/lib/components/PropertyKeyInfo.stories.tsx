import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { PropertyKeyInfo } from './PropertyKeyInfo'

export default {
    title: 'PostHog/Components/PropertyKeyInfo',
    component: PropertyKeyInfo,
} as ComponentMeta<typeof PropertyKeyInfo>

const Template: ComponentStory<typeof PropertyKeyInfo> = (args) => <PropertyKeyInfo {...args} />

export const Primary = Template.bind({})
Primary.args = {
    value: '$current_url',
    type: 'event',
    tooltipPlacement: undefined,
    disablePopover: false,
    disableIcon: false,
    ellipsis: true,
}
