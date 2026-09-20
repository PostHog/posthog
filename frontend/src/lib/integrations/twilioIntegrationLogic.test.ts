import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twilioIntegrationLogic } from './twilioIntegrationLogic'

describe('twilioIntegrationLogic', () => {
    let logic: ReturnType<typeof twilioIntegrationLogic.build>
    let phoneNumbersResponse: [number, Record<string, any>]

    const failureDetail = 'PostHog could not reach Twilio to load phone numbers. Try again in a few minutes.'
    const okResponse: [number, Record<string, any>] = [
        200,
        {
            phone_numbers: [{ sid: 'PN1', phone_number: '+15550000001', friendly_name: 'Support line' }],
            lastRefreshedAt: '2026-01-01T00:00:00Z',
        },
    ]

    beforeEach(() => {
        phoneNumbersResponse = okResponse
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/twilio_phone_numbers': () => phoneNumbersResponse,
            },
        })
        initKeaTests()
        logic = twilioIntegrationLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('leaves an account that owns no phone numbers without an error', async () => {
        phoneNumbersResponse = [200, { phone_numbers: [], lastRefreshedAt: '2026-01-01T00:00:00Z' }]

        await expectLogic(logic, () => {
            logic.actions.loadAllTwilioPhoneNumbers()
        }).toFinishAllListeners()

        expect(logic.values.twilioPhoneNumbers).toEqual([])
        expect(logic.values.twilioPhoneNumbersErrorMessage).toBeNull()
    })

    it('surfaces a Twilio failure inline without a failure toast', async () => {
        phoneNumbersResponse = [502, { type: 'server_error', code: 'twilio_unavailable', detail: failureDetail }]

        await expectLogic(logic, () => {
            logic.actions.loadAllTwilioPhoneNumbers()
        })
            .toDispatchActions(['setTwilioPhoneNumbersError', 'loadAllTwilioPhoneNumbersSuccess'])
            .toNotHaveDispatchedActions(['loadAllTwilioPhoneNumbersFailure'])

        expect(logic.values.twilioPhoneNumbersErrorMessage).toBe(failureDetail)
    })

    it('keeps previously loaded phone numbers when a later load fails, and clears the error on success', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadAllTwilioPhoneNumbers()
        }).toFinishAllListeners()
        expect(logic.values.twilioPhoneNumbers.map((x) => x.sid)).toEqual(['PN1'])

        phoneNumbersResponse = [
            400,
            {
                type: 'validation_error',
                code: 'twilio_integration_invalid_credentials',
                detail: 'Twilio rejected your account SID and auth token.',
            },
        ]
        await expectLogic(logic, () => {
            logic.actions.loadAllTwilioPhoneNumbers(true)
        }).toFinishAllListeners()

        expect(logic.values.twilioPhoneNumbers.map((x) => x.sid)).toEqual(['PN1'])
        expect(logic.values.twilioPhoneNumbersErrorMessage).toBe('Twilio rejected your account SID and auth token.')

        phoneNumbersResponse = okResponse
        await expectLogic(logic, () => {
            logic.actions.loadAllTwilioPhoneNumbers(true)
        }).toFinishAllListeners()

        expect(logic.values.twilioPhoneNumbersErrorMessage).toBeNull()
    })
})
