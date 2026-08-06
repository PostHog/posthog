import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { CouponRedemption } from './CouponRedemption'

const meta: Meta = {
    title: 'Scenes-Other/Coupon redemption',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-10',
        testOptions: {
            viewport: {
                width: 1300,
                height: 900,
            },
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/billing/coupons/overview': {
                    claimed_coupons: [],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Generic entry point reached from the billing page — no campaign, so just the code-entry form.
export const GenericEntry: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, has_active_subscription: true },
            },
        })
        return <CouponRedemption campaign="" />
    },
}

// Campaign link from a marketing email — full hero and benefits alongside the form.
export const Campaign: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, has_active_subscription: true },
            },
        })
        return <CouponRedemption campaign="lenny" />
    },
}

// Landed without a paid plan — the paid-plan gate is one of the dead ends we now instrument.
export const NeedsPaidPlan: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, has_active_subscription: false },
            },
        })
        return <CouponRedemption campaign="lenny" />
    },
}

// Unknown campaign slug — renders a Not found page instead of a silent exit.
export const UnknownCampaign: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': { ...billingJson, has_active_subscription: true },
            },
        })
        return <CouponRedemption campaign="does-not-exist" />
    },
}
