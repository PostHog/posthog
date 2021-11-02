import React from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'

import { PayCard } from './PayCard'
import { AvailableFeature } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { initKea } from '~/initKea'
import { Provider } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export default {
    title: 'PostHog/Components/PayCard',
    component: PayCard,
    // parameters: { options: { showPanel: true } },
} as ComponentMeta<typeof PayCard>

const Template: ComponentStory<typeof PayCard> = (args) => {
    initKea()
    preflightLogic.mount()
    eventUsageLogic.mount()
    return (
        <Provider>
            <div style={{ maxWidth: 600 }}>
                <PayCard {...args} />
            </div>
        </Provider>
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
