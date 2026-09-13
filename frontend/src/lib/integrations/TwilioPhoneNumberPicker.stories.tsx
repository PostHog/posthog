import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { TwilioPhoneNumberPicker } from './TwilioIntegrationHelpers'

const integration = mockIntegration

const phoneNumbers = [
    { sid: 'PN1', phone_number: '+15550000001', friendly_name: 'Support line' },
    { sid: 'PN2', phone_number: '+15550000002', friendly_name: 'Onboarding line' },
]

function mockPhoneNumbers(response: Record<string, any> | [number, Record<string, any>]): void {
    useStorybookMocks({
        get: {
            '/api/projects/:id/integrations/:intId/twilio_phone_numbers': response,
            '/api/environments/:id/integrations/:intId/twilio_phone_numbers': response,
        },
    })
}

const meta: Meta = {
    title: 'Components/Twilio phone number picker',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

type Story = StoryObj

export const PhoneNumbersOwned: Story = {
    render: () => {
        mockPhoneNumbers({ phone_numbers: phoneNumbers, lastRefreshedAt: '2026-01-01T00:00:00Z' })
        return (
            <div className="p-4 max-w-md">
                <TwilioPhoneNumberPicker integration={integration} onChange={() => {}} />
            </div>
        )
    },
}

// An account that has not bought a number yet. This is a normal setup state, not a failure.
export const NoPhoneNumbersOwned: Story = {
    render: () => {
        mockPhoneNumbers({ phone_numbers: [], lastRefreshedAt: '2026-01-01T00:00:00Z' })
        return (
            <div className="p-4 max-w-md">
                <TwilioPhoneNumberPicker integration={integration} onChange={() => {}} />
            </div>
        )
    },
}

export const TwilioFailed: Story = {
    render: () => {
        mockPhoneNumbers([
            502,
            {
                type: 'server_error',
                code: 'twilio_unavailable',
                detail: 'PostHog could not reach Twilio to load phone numbers. Try again in a few minutes.',
            },
        ])
        return (
            <div className="p-4 max-w-md">
                <TwilioPhoneNumberPicker integration={integration} onChange={() => {}} />
            </div>
        )
    },
}
