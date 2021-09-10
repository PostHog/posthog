import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { PropertyKeyInfo } from './PropertyKeyInfo'

export default {
    title: 'PostHog/Components/PropertyKeyInfo',
    component: PropertyKeyInfo,
    parameters: { options: { showPanel: true } },
} as ComponentMeta<typeof PropertyKeyInfo>

const Template: ComponentStory<typeof PropertyKeyInfo> = (args) => {
    return args.value ? (
        <PropertyKeyInfo {...args} />
    ) : (
        <>
            <div>
                <PropertyKeyInfo {...args} value="$current_url" />
            </div>
            <div>
                <PropertyKeyInfo {...args} value="$country" />
            </div>
            <div>
                <PropertyKeyInfo {...args} value="booking submitted" />
            </div>
        </>
    )
}

export const Primary = Template.bind({})
Primary.args = {
    value: undefined,
    type: 'event',
    tooltipPlacement: undefined,
    disablePopover: false,
    disableIcon: false,
    ellipsis: true,
}
