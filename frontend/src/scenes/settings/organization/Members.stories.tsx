import { Meta, StoryObj } from '@storybook/react'

import { STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'

const meta: Meta = {
    component: App,
    title: 'Scenes-Other/Org Members',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: STORYBOOK_FEATURE_FLAGS,
        pageUrl: urls.settings('organization-members'),
    },
    decorators: [
        mswDecorator({
            get: {
                // Billing resolves no product, so PayGateMini draws no paywall and renders the
                // member permission switches instead.
                '/api/billing/': (): MockSignature => [404, { detail: 'Not found.' }],
                // Otherwise the member notifications section sits on a spinner and the snapshot
                // depends on timing.
                '/api/organizations/:id/notification_locks/': [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SelfHostedWithoutBilling: Story = {}
