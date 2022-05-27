import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { PropertyKeyInfo } from './PropertyKeyInfo'

export default {
    title: 'Components/Property Key Info',
    component: PropertyKeyInfo,
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
                <PropertyKeyInfo {...args} value="$feature/some-feature-key" />
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

export const PropertyKeyInfo_ = Template.bind({})
PropertyKeyInfo_.args = {
    value: undefined,
    type: 'event',
    tooltipPlacement: undefined,
    disablePopover: false,
    disableIcon: false,
    ellipsis: true,
}
