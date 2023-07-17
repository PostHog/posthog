import { Meta } from '@storybook/react'
import { Billing } from './Billing'
import { useStorybookMocks, mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import billingJson from '~/mocks/fixtures/_billing_v2.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_v2_with_discount.json'

export default {
    title: 'Scenes-Other/Billing v2',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-05-25',
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

export const _BillingV2 = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJson,
            },
        },
    })

    return <Billing />
}

export const BillingV2WithDiscount = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJsonWithDiscount,
            },
        },
    })

    return <Billing />
}
