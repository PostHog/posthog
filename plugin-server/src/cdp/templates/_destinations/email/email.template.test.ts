import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './email.template'

describe('email template', () => {
    const tester = new TemplateTester(template)

    const createEmailParams = (
        params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
    ): CyclotronInvocationQueueParametersEmailType => {
        return {
            type: 'email',
            integrationId: 1,
            to: {
                email: 'test@example.com',
                name: 'Test User',
            },
            from: {
                email: 'test@posthog.com',
                name: 'Test User',
            },
            subject: 'Test Subject',
            text: 'Test Text',
            html: 'Test HTML',
            ...params,
        }
    }

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                email: createEmailParams({
                    to: {
                        email: 'test@example.com',
                        name: 'Test User',
                    },
                }),
            },
            {
                event: {
                    properties: {
                        $lib_version: '1.0.0',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "from": {
                "email": "test@posthog.com",
                "name": "Test User",
              },
              "html": "Test HTML",
              "integrationId": 1,
              "subject": "Test Subject",
              "text": "Test Text",
              "to": {
                "email": "test@example.com",
                "name": "Test User",
              },
              "type": "email",
            }
        `)

        const emailResponse = await tester.invokeEmailResponse(response.invocation, {
            success: true,
        })

        expect(emailResponse.finished).toBe(true)
        expect(emailResponse.error).toBeUndefined()
    })
})
