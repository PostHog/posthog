import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useValues } from 'kea'
import { Slide, ToastContainer } from 'react-toastify'

import { OrganizationMembershipLevel } from 'lib/constants'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'

import { expect } from 'storybook/test'

import { Coupons } from './Coupons'

const meta: Meta<typeof Coupons> = {
    title: 'Scenes-Other/Coupons/Community',
    component: Coupons,
    args: { campaign: 'community' },
    parameters: {
        layout: 'padded',
        mockDate: '2026-09-21',
        pageUrl: '/coupons/community',
        msw: {
            mocks: {
                get: {
                    '/api/billing/': { ...billingJson, has_active_subscription: true },
                    '/api/billing/coupons/overview': { claimed_coupons: [] },
                },
                post: {
                    '/api/billing/coupons/claim': {
                        success: true,
                        code: 'CMP-TESTCODE',
                        campaign: 'Community points pilot',
                        expires_at: '2027-09-21',
                    },
                },
            },
        },
    },
    decorators: [mswDecorator({})],
    render: (args, { globals }) => {
        const { currentOrganization } = useValues(organizationLogic)
        return (
            <>
                <ToastContainer
                    position="bottom-center"
                    autoClose={false}
                    transition={Slide}
                    closeButton={<ToastCloseButton />}
                    theme={globals.theme === 'dark' ? 'dark' : 'light'}
                />
                {currentOrganization && <Coupons {...args} />}
            </>
        )
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Ready: Story = {
    parameters: { testOptions: { viewportWidths: ['narrow', 'wide'] } },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText("You're on a paid plan")
        await canvas.findByText('Redeem your community points')
        await canvas.findByText('Applied to your next invoices. Valid for 12 months. Not for AI products.')
        await canvas.findByText(
            'To claim for a different organization, switch to that organization first. One code per organization.'
        )
        await expect(canvas.getByLabelText('PostHog organization')).toBeDisabled()
        await expect(canvas.getByLabelText('PostHog organization')).toHaveValue(MOCK_DEFAULT_ORGANIZATION.name)
        await expect(canvas.getByRole('button', { name: 'Redeem coupon' })).toBeEnabled()
    },
}

export const Redeemed: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText("You're on a paid plan")
        await userEvent.type(await canvas.findByPlaceholderText('XXX-XXXXXXXXXXX'), 'CMP-TESTCODE')
        await userEvent.click(canvas.getByRole('button', { name: 'Redeem coupon' }))
        await canvas.findByText('Coupon redeemed successfully!')
        await canvas.findByRole('link', { name: 'View in billing' })
    },
}

export const InvalidCode: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
        msw: {
            mocks: {
                post: {
                    '/api/billing/coupons/claim': [400, { type: 'validation_error', detail: 'Invalid coupon code' }],
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText("You're on a paid plan")
        await userEvent.type(await canvas.findByPlaceholderText('XXX-XXXXXXXXXXX'), 'CMP-INVALID')
        await userEvent.click(canvas.getByRole('button', { name: 'Redeem coupon' }))
        await within(document.body).findAllByText('Invalid coupon code')
    },
}

export const AlreadyClaimed: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/billing/coupons/overview': {
                        claimed_coupons: [
                            {
                                code: 'CMP-TESTCODE',
                                campaign_name: 'Community points pilot',
                                campaign_slug: 'community',
                                claimed_at: '2026-09-21T12:00:00Z',
                                expires_at: '2027-09-21',
                                status: 'claimed',
                            },
                        ],
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText("You've already claimed this offer!")
        await expect(canvas.queryByPlaceholderText('XXX-XXXXXXXXXXX')).not.toBeInTheDocument()
    },
}

export const SubscriptionRequired: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/billing/': { ...billingJson, has_active_subscription: false },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('To claim this coupon, you need to be on a paid plan.')
        await userEvent.type(await canvas.findByPlaceholderText('XXX-XXXXXXXXXXX'), 'CMP-TESTCODE')
        await userEvent.click(canvas.getByRole('button', { name: 'Redeem coupon' }))
        await canvas.findByText('You need to be on a paid plan before claiming this coupon')
        await expect(canvas.queryByText('Coupon redeemed successfully!')).not.toBeInTheDocument()
    },
}

export const Member: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/organizations/@current/': {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        membership_level: OrganizationMembershipLevel.Member,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Admin or owner permission required')
        await expect(canvas.queryByPlaceholderText('XXX-XXXXXXXXXXX')).not.toBeInTheDocument()
    },
}
