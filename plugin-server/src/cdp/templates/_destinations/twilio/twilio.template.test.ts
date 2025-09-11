import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './twilio.template'

describe('twilio template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                twilio_account: {
                    account_sid: 'sid_12345',
                    auth_token: 'auth_12345',
                },
                from_number: '+1234567891',
            },
            {
                event: {
                    event: 'event-name',
                },
                person: {
                    properties: {
                        phone: '+1234567893',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "To=%2B1234567893&From=%2B1234567891&Body=PostHog%20event%20event-name%20was%20triggered",
              "headers": {
                "Authorization": "Basic c2lkXzEyMzQ1OmF1dGhfMTIzNDU=",
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.twilio.com/2010-04-01/Accounts/sid_12345/Messages.json",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { message: 'Hello, world!' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
})
