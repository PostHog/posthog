import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { PayCard } from './PayCard'
import { AvailableFeature } from '~/types'

export default {
    title: 'Components/PayCard',
    component: PayCard,
} as ComponentMeta<typeof PayCard>

const Template: ComponentStory<typeof PayCard> = (args) => {
    return (
        <div style={{ maxWidth: 600 }}>
            <PayCard {...args} />
        </div>
    )
}

export const Primary = Template.bind({})
Primary.args = {
    identifier: AvailableFeature.PATHS_ADVANCED,
    title: 'Get a deeper understanding of your users',
    caption:
        'Advanced features such as interconnection with funnels, grouping & wildcarding and exclusions can help you gain deeper insights.',
    docsLink: 'https://posthog.com/docs/user-guides/paths',
}
