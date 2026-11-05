import type { Meta, StoryObj } from '@storybook/react'
import type { ComponentProps } from 'react'

import { WebhookNotRegisteredBanner } from './WebhookNotRegisteredBanner'

// LemonBanner is a CSS container, so it collapses without an explicitly sized parent.
const renderInSizedParent = (props: ComponentProps<typeof WebhookNotRegisteredBanner>): JSX.Element => {
    return (
        <div id="target" className="w-200">
            <WebhookNotRegisteredBanner {...props} />
        </div>
    )
}

type Story = StoryObj<typeof WebhookNotRegisteredBanner>
const meta: Meta<typeof WebhookNotRegisteredBanner> = {
    title: 'Scenes-App/Data Warehouse/Settings/Webhook not registered banner',
    component: WebhookNotRegisteredBanner,
    parameters: {
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            snapshotTargetSelector: '#target',
        },
    },
    args: {
        sourceName: 'Stripe',
        onSetUpWebhook: () => {},
        onChangeSyncMethod: () => {},
    },
}

export default meta

export const ManyTables: Story = {
    render: renderInSizedParent,
    args: {
        tableNames: ['Customer', 'Invoice', 'Charge', 'Subscription', 'Price', 'Product', 'Refund'],
    },
}
