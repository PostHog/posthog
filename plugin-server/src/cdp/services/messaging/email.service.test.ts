// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import crypto from 'crypto'
import express from 'express'

import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import { EmailService } from './email.service'
import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { CdpApi } from '~/cdp/cdp-api'
import supertest from 'supertest'
import { setupExpressApp } from '~/router'

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

    describe('handleWebhook', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application

        beforeEach(() => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())
        })

        it('should return 403 if required headers are missing', async () => {
            const res = await supertest(app).post(`/public/messaging/mailjet_webhook`).send({})

            expect(res.status).toBe(403)
            expect(res.body).toMatchInlineSnapshot(`
                {
                  "message": "Missing required headers or body",
                }
            `)
        })

        it('should return 403 if signature is invalid', async () => {
            const timestamp = Date.now().toString()
            const res = await supertest(app)
                .post(`/public/messaging/mailjet_webhook`)
                .set({
                    'x-mailjet-signature': 'invalid-signature',
                    'x-mailjet-timestamp': timestamp,
                })
                .send({
                    event: 'sent',
                    time: Date.now(),
                    email: 'test@example.com',
                    mj_campaign_id: 1,
                    mj_contact_id: 1,
                    message_id: 'test-message-id',
                    custom_id: 'test-custom-id',
                    payload: {},
                })

            expect(res.status).toBe(403)
            expect(res.body).toMatchInlineSnapshot(`
                {
                  "message": "Invalid signature",
                }
            `)
        })

        it('should process valid webhook events', async () => {
            const timestamp = Date.now().toString()
            const payload = JSON.stringify({
                event: 'sent',
                time: Date.now(),
                email: 'test@example.com',
                mj_campaign_id: 1,
                mj_contact_id: 1,
                message_id: 'test-message-id',
                custom_id: 'test-custom-id',
                payload: {},
            })
            const signature = crypto
                .createHmac('sha256', hub.MAILJET_SECRET_KEY)
                .update(`${timestamp}.${payload}`)
                .digest('hex')

            const res = await supertest(app)
                .post(`/public/messaging/mailjet_webhook`)
                .set({
                    'x-mailjet-signature': signature,
                    'x-mailjet-timestamp': timestamp,
                    'content-type': 'application/json',
                })
                .send(payload)

            expect(res.status).toBe(200)
            expect(res.body).toMatchInlineSnapshot(`
                {
                  "message": "OK",
                }
            `)
        })

        it.each([
            {
                event: 'open',
                extraFields: {
                    ip: '127.0.0.1',
                    geo: 'US',
                    agent: 'Mozilla',
                },
            },
            {
                event: 'click',
                extraFields: {
                    url: 'https://example.com',
                },
            },
            {
                event: 'bounce',
                extraFields: {
                    blocked: false,
                    hard_bounce: true,
                    error: 'test error',
                },
            },
            {
                event: 'spam',
                extraFields: {
                    source: 'test source',
                },
            },
            {
                event: 'unsub',
                extraFields: {
                    mj_list_id: '123',
                },
            },
        ])('should handle $event event', async ({ event, extraFields }) => {
            const timestamp = Date.now().toString()
            const payload = JSON.stringify({
                event,
                time: Date.now(),
                email: 'test@example.com',
                mj_campaign_id: 1,
                mj_contact_id: 1,
                message_id: 'test-message-id',
                custom_id: 'test-custom-id',
                payload: {},
                ...extraFields,
            })
            const signature = crypto
                .createHmac('sha256', hub.MAILJET_SECRET_KEY)
                .update(`${timestamp}.${payload}`)
                .digest('hex')

            const res = await supertest(app)
                .post(`/public/messaging/mailjet_webhook`)
                .set({
                    'x-mailjet-signature': signature,
                    'x-mailjet-timestamp': timestamp,
                    'content-type': 'application/json',
                })
                .send(payload)

            expect(res.status).toBe(200)
            expect(res.body).toEqual({ message: 'OK' })
        })
    })
})
