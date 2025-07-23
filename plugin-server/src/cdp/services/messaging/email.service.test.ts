// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import { EmailService } from './email.service'
import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

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

describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            MAILJET_SECRET_KEY: 'mailjet-secret-key',
            MAILJET_PUBLIC_KEY: 'mailjet-public-key',
        })
        team = await getFirstTeam(hub)
        service = new EmailService(hub)

        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('executeSendEmail', () => {
        let invocation: CyclotronJobInvocationHogFunction

        beforeEach(async () => {
            await insertIntegration(hub.postgres, team.id, {
                id: 1,
                kind: 'email',
                config: {
                    domain: 'posthog.com',
                    mailjet_verified: true,
                },
            })

            invocation = createExampleInvocation({
                team_id: team.id,
                id: 'function-1',
            })
            invocation.id = 'invocation-1'
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = createEmailParams({ integrationId: 1 })
        })

        describe('integration validation', () => {
            beforeEach(async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: 2,
                    kind: 'email',
                    config: {
                        domain: 'other-domain.com',
                        mailjet_verified: false,
                    },
                })

                await insertIntegration(hub.postgres, team.id, {
                    id: 3,
                    kind: 'slack',
                    config: {},
                })
            })

            it('should validate if the integration is not found', async () => {
                invocation.queueParameters = createEmailParams({ integrationId: 100 })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })

            it('should validate if the integration is not an email integration', async () => {
                invocation.queueParameters = createEmailParams({ integrationId: 3 })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })

            it('should validate if the integration is not the correct team', async () => {
                invocation.teamId = 100
                invocation.queueParameters = createEmailParams({ integrationId: 1 })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })

            it('should validate if the email domain is not the same as the integration domain', async () => {
                invocation.queueParameters = createEmailParams({
                    integrationId: 1,
                    from: { email: 'test@other-domain.com', name: '' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"The selected email integration domain (posthog.com) does not match the 'from' email domain (other-domain.com)"`
                )
            })

            it('should validate if the email domain is not verified', async () => {
                invocation.queueParameters = createEmailParams({
                    integrationId: 2,
                    from: { email: 'test@other-domain.com', name: '' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"The selected email integration domain is not verified"`)
            })

            it('should allow a valid email integration and domain', async () => {
                invocation.queueParameters = createEmailParams({ integrationId: 1 })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
            })
        })

        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
                    [
                      "https://api.mailjet.com/v3.1/send",
                      {
                        "body": "{"Messages":[{"From":{"Email":"test@posthog.com","Name":"Test User"},"To":[{"Email":"test@example.com","Name":"Test User"}],"Subject":"Test Subject","TextPart":"Test Text","HTMLPart":"Test HTML","CustomID":"ph_fn_id=function-1&ph_inv_id=invocation-1"}]}",
                        "headers": {
                          "Authorization": "Basic bWFpbGpldC1wdWJsaWMta2V5Om1haWxqZXQtc2VjcmV0LWtleQ==",
                          "Content-Type": "application/json",
                        },
                        "method": "POST",
                      },
                    ]
                `)
            })
        })
    })
})
