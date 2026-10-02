import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { paymentEntryLogic } from './paymentEntryLogic'
import { PaymentEntryModal } from './PaymentEntryModal'

const meta: Meta = {
    title: 'Scenes-Other/Billing/Payment entry modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-10',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/api/billing/': { ...billingJson },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

const OpenPaymentEntryModal = (): JSX.Element => {
    const { showPaymentEntryModal } = useActions(paymentEntryLogic)
    useEffect(() => {
        showPaymentEntryModal()
    }, [showPaymentEntryModal])
    return <PaymentEntryModal />
}

export const ApiError: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/billing/activate/authorize': () => [
                    403,
                    { detail: "You've been blocked from subscribing. Please contact support." },
                ],
            },
        })
        return <OpenPaymentEntryModal />
    },
}

// Stripe.js has no publishable key in Storybook, so the form shows the "couldn't load" banner.
export const StripeError: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/billing/activate/authorize': { clientSecret: 'pi_example_secret_example' },
            },
        })
        return <OpenPaymentEntryModal />
    },
}
