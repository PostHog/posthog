import { Meta } from '@storybook/react'
import { BillingSubscribed } from './BillingSubscribed'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { BillingLocked } from './BillingLocked'

export default {
    title: 'Scenes-Other/Billing',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        chromatic: { disableSnapshot: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
} as Meta

export const Subscribed = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.billingSubscribed(), { s: 'success' })
    })
    return <BillingSubscribed />
}
export const Locked = (): JSX.Element => {
    return <BillingLocked />
}
