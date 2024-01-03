import { Meta } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import billingJson from '~/mocks/fixtures/_billing_v2.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_v2_with_discount.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { Billing } from './Billing'

const meta: Meta = {
    title: 'Scenes-Other/Billing v2',
    parameters: {
        layout: 'fullscreen',
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
}
export default meta
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
