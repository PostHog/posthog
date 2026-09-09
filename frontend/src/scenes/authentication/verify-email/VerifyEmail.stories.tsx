import type { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { VerifyEmail } from './VerifyEmail'
import { type VerifyEmailReason, verifyEmailLogic } from './verifyEmailLogic'

type VerifyEmailView = 'pending' | 'success' | 'invalid'

type StoryArgs = {
    view: VerifyEmailView
    reason?: VerifyEmailReason
    verificationEmailSent?: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Verify Email',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        view: {
            control: 'select',
            name: 'View',
            options: ['pending', 'success', 'invalid'] satisfies VerifyEmailView[],
        },
        reason: {
            control: 'select',
            name: 'Deep link reason',
            options: [undefined, 'stripe_deep_link', 'partner_deep_link'],
        },
        verificationEmailSent: {
            control: 'boolean',
            name: 'Verification email sent',
        },
    },
    args: {
        view: 'pending',
        verificationEmailSent: true,
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ view, reason, verificationEmailSent = true }) => {
    useStorybookMocks({
        get: {
            '/_preflight': { ...preflightJson },
            '/api/users/@me': () => [200, { email: 'test@posthog.com', first_name: 'Test' }],
        },
    })

    useEffect(() => {
        verifyEmailLogic.actions.setView(view)
        verifyEmailLogic.actions.setUuid('12345678')
        verifyEmailLogic.actions.setDeepLinkContext(reason ?? null, verificationEmailSent)
    }, [view, reason, verificationEmailSent])

    return <VerifyEmail />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const Pending: StoryFn<StoryArgs> = Template.bind({})
Pending.args = { view: 'pending' }

export const Success: StoryFn<StoryArgs> = Template.bind({})
Success.args = { view: 'success' }

export const Invalid: StoryFn<StoryArgs> = Template.bind({})
Invalid.args = { view: 'invalid' }

export const PendingFromStripeDeepLink: StoryFn<StoryArgs> = Template.bind({})
PendingFromStripeDeepLink.args = { view: 'pending', reason: 'stripe_deep_link' }

export const PendingWithFailedSend: StoryFn<StoryArgs> = Template.bind({})
PendingWithFailedSend.args = { view: 'pending', reason: 'stripe_deep_link', verificationEmailSent: false }
