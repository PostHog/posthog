import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'
import { parseJSON } from '~/utils/json-parse'

import { Hub, Team } from '../../../types'
import { EmailService } from './email.service'
import { MailDevAPI } from './helpers/maildev'

const createEmailParams = (
    params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType => {
    return {
        type: 'email',
        to: { email: 'test@example.com', name: 'Test User' },
        from: { email: 'test@posthog.com', name: 'Test User', integrationId: 1 },
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
        hub = await createHub({ MAILJET_SECRET_KEY: 'mailjet-secret-key', MAILJET_PUBLIC_KEY: 'mailjet-public-key' })
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
                config: { email: 'test@posthog.com', name: 'Test User', domain: 'posthog.com', mailjet_verified: true },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1, email: 'test@posthog.com' } })
        })
        describe('integration validation', () => {
            beforeEach(async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: 2,
                    kind: 'email',
                    config: {
                        email: 'test@other-domain.com',
                        name: 'Test User',
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
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 100, email: 'test@posthog.com' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })
            it('should validate if the integration is not an email integration', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 3, email: 'test@posthog.com' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })
            it('should validate if the integration is not the correct team', async () => {
                invocation.teamId = 100
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email: 'test@posthog.com' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"Email integration not found"`)
            })
            it('should ignore a given email and use the integration config', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email: 'test@other-domain.com', name: '' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(parseJSON(mockFetch.mock.calls[0][1].body).Messages[0].From).toMatchInlineSnapshot(
                    `
                    {
                      "Email": "test@posthog.com",
                      "Name": "Test User",
                    }
                `
                )
            })
            it('should validate if the email domain is not verified', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 2, email: 'test@other-domain.com', name: '' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"The selected email integration domain is not verified"`)
            })
            it('should allow a valid email integration and domain', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email: 'test@posthog.com' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
            })
        })
        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(
                    `
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
                `
                )
            })
        })
    })
    describe('native email sending', () => {
        let invocation: CyclotronJobInvocationHogFunction
        const mailDevAPI = new MailDevAPI()

        beforeEach(async () => {
            const actualFetch = jest.requireActual('~/utils/request').fetch as jest.Mock
            mockFetch.mockImplementation((...args: any[]): Promise<any> => {
                return actualFetch(...args) as any
            })
            hub.MAILJET_PUBLIC_KEY = ''
            hub.MAILJET_SECRET_KEY = ''
            await insertIntegration(hub.postgres, team.id, {
                id: 1,
                kind: 'email',
                config: { email: 'test@posthog.com', name: 'Test User', domain: 'posthog.com', mailjet_verified: true },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1, email: 'test@posthog.com' } })
            await mailDevAPI.clearEmails()
        })

        it('should send an email', async () => {
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const emails = await mailDevAPI.getEmails()
            expect(emails).toHaveLength(1)
            expect(emails[0]).toMatchObject({
                from: [
                    {
                        address: 'test@posthog.com',
                        name: 'Test User',
                    },
                ],
                html: 'Test HTML',
                subject: 'Test Subject',
                text: 'Test Text',
                to: [
                    {
                        address: 'test@example.com',
                        name: 'Test User',
                    },
                ],
            })
        })

        it('should include tracking code in the email', async () => {
            invocation.queueParameters = createEmailParams({
                html: '<body>Hi! <a href="https://example.com">Click me</a></body>',
            })
            await service.executeSendEmail(invocation)
            const emails = await mailDevAPI.getEmails()
            expect(emails[0].html).toEqual(
                `<body>Hi! <a href="http://localhost:8010/public/m/redirect?ph_fn_id=function-1&ph_inv_id=invocation-1&target=https%3A%2F%2Fexample.com">Click me</a><img src="http://localhost:8010/public/m/pixel?ph_fn_id=function-1&ph_inv_id=invocation-1" style="display: none;" /></body>`
            )
        })
    })
})
