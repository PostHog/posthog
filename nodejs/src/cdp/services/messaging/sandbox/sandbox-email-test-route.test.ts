import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { setupExpressApp } from '~/common/api/router'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'

import { CyclotronJobInvocationHogFlow } from '../../../types'
import { createInvocationResult } from '../../../utils/invocation-utils'
import { HogInputsService } from '../../hog-inputs.service'
import { ActionHandlerOptions } from '../../hogflows/actions/action.interface'
import { SandboxEmailAction } from '../../hogflows/actions/email_sandbox'
import { RecipientTokensService } from '../recipient-tokens.service'
import { SANDBOX_TEST_SEND_PATH, sandboxEmailTestRouter } from './sandbox-email-test-route'
import { SandboxEmailTester, SandboxEmailTesterDeps } from './sandbox-email-tester'
import { SandboxSendOutcome } from './sandbox-email.service'

describe('sandbox email test sends', () => {
    const secret = 'sandbox-test-secret'
    const workerJwt = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, secret)
    let hogFlow: HogFlow
    let send: jest.Mock<Promise<SandboxSendOutcome>>
    let capture: jest.Mock
    let app: express.Application
    let server: Server

    const serveWorker = (service: { send: typeof send } | null): void => {
        app = setupExpressApp({ internalApiSecret: 'shared-internal-secret' })
        app.use(sandboxEmailTestRouter({ jwt: workerJwt, service, events: { capture } }))
        server = app.listen(0, () => {})
    }

    beforeEach(() => {
        send = jest.fn().mockResolvedValue({ status: 'accepted', messageId: 'ses-1' })
        capture = jest.fn().mockResolvedValue(undefined)
        serveWorker({ send })
        hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                    email: {
                        type: 'email_sandbox',
                        config: {
                            message_category_id: 'news',
                            message_category_type: 'marketing',
                            inputs: {
                                email: {
                                    templating: 'liquid',
                                    value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi', text: 'x' },
                                },
                            },
                        },
                    },
                },
                edges: [{ from: 'trigger', to: 'email', type: 'continue' }],
            })
            .build()
    })

    afterEach(() => {
        server.close()
    })

    const fetchThroughWorker = jest.fn(async (url: string, options: any): Promise<FetchResponse> => {
        const response = await supertest(app)
            .post(new URL(url).pathname)
            .set(options.headers)
            .send(parseJSON(options.body))
        return {
            status: response.status,
            headers: {},
            json: () => Promise.resolve(response.body),
            text: () => Promise.resolve(response.text),
            dump: () => Promise.resolve(),
        }
    })

    const tester = (fetch: SandboxEmailTesterDeps['fetch'] = fetchThroughWorker): SandboxEmailTester =>
        new SandboxEmailTester({
            hogInputsService: new HogInputsService(
                {} as any,
                new RecipientTokensService('00beef0000beef0000beef0000beef00', 'http://localhost:8000'),
                {} as any
            ),
            siteUrl: 'http://localhost:8000',
            endpoint: 'http://sandbox-worker.internal',
            jwt: new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, secret),
            fetch,
        })

    const testRun = (
        hogExecutorOptions: ActionHandlerOptions<SandboxEmailAction>['hogExecutorOptions'] = {}
    ): ActionHandlerOptions<SandboxEmailAction> => {
        const invocation = createExampleHogFlowInvocation(
            hogFlow,
            { currentAction: { id: 'email', startedAtTimestamp: 0 } },
            {
                properties: { email: 'member@example.com' },
            }
        )
        return {
            invocation,
            action: hogFlow.actions.find((action) => action.id === 'email') as SandboxEmailAction,
            result: createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {}),
            hogExecutorOptions: { isTest: true, ...hogExecutorOptions },
        }
    }

    it('renders in cdp-api and sends inline on the sandbox worker as a test', async () => {
        await expect(tester().send(testRun())).resolves.toEqual({ status: 'accepted', message_id: 'ses-1' })

        expect(send).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: hogFlow.team_id,
                hogFlowId: hogFlow.id,
                actionId: 'email',
                isTest: true,
                email: { to: { email: 'member@example.com' }, subject: 'Hi', text: 'x' },
                categoryId: 'news',
                categoryType: 'marketing',
            })
        )
        expect(capture).toHaveBeenCalledWith(hogFlow.team_id, 'accepted', {
            workflow_id: hogFlow.id,
            action_id: 'email',
            is_test: true,
        })
    })

    it('sends a test of a workflow that is not saved yet', async () => {
        hogFlow.id = 'new'

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'accepted', message_id: 'ses-1' })
        expect(send).toHaveBeenCalledWith(expect.objectContaining({ hogFlowId: 'new', isTest: true }))
    })

    it.each<[string, SandboxSendOutcome, object]>([
        [
            'a retryable refusal',
            { status: 'retry', reason: 'cap_storage_unavailable' },
            { status: 'pending', reason: 'cap_storage_unavailable' },
        ],
        ['a block', { status: 'skipped', reason: 'not_member' }, { status: 'skipped', reason: 'not_member' }],
    ])('reports %s from the worker', async (_name, outcome, expected) => {
        send.mockResolvedValue(outcome)

        await expect(tester().send(testRun())).resolves.toEqual(expected)
    })

    it('skips the test when the worker has sending off', async () => {
        server.close()
        serveWorker(null)

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'skipped', reason: 'sending_disabled' })
    })

    it.each([
        ['no token', undefined],
        ['a token for another audience', new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_STEP_RESUME, secret)],
        ['a token signed with another key', new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, 'x')],
    ])('refuses a request with %s', async (_name, jwt) => {
        const token = jwt?.mint({ team_id: hogFlow.team_id, hog_flow_id: hogFlow.id })
        const request = supertest(app).post(SANDBOX_TEST_SEND_PATH.replace(':team_id', String(hogFlow.team_id)))

        const response = await (token ? request.set('Authorization', `Bearer ${token}`) : request).send({
            hog_flow_id: hogFlow.id,
            action_id: 'email',
            email: {},
        })

        expect(response.status).toBe(403)
        expect(send).not.toHaveBeenCalled()
    })

    it.each([
        ['a token for another team', (teamId: number) => ({ team_id: teamId + 1, hog_flow_id: hogFlow.id }), 60],
        [
            'a token for another workflow',
            (teamId: number) => ({ team_id: teamId, hog_flow_id: '0190f0f0-0000-7000-8000-00000000000f' }),
            60,
        ],
        ['an expired token', (teamId: number) => ({ team_id: teamId, hog_flow_id: hogFlow.id }), -120],
    ])('refuses %s', async (_name, claims, ttlSeconds) => {
        const token = workerJwt.mint(claims(hogFlow.team_id), ttlSeconds)

        const response = await supertest(app)
            .post(SANDBOX_TEST_SEND_PATH.replace(':team_id', String(hogFlow.team_id)))
            .set('Authorization', `Bearer ${token}`)
            .send({ hog_flow_id: hogFlow.id, action_id: 'email', email: {} })

        expect(response.status).toBe(403)
        expect(send).not.toHaveBeenCalled()
    })

    it('mocks a test run after rendering, with no network', async () => {
        const fetch = jest.fn()

        await expect(tester(fetch).send(testRun({ functions: {} }))).resolves.toEqual({ status: 'accepted' })

        const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
        ;(action.config as any).inputs.email.value.subject = ''
        const failedRun = testRun({ functions: {} })
        await expect(tester(fetch).send(failedRun)).resolves.toEqual({
            status: 'failed',
            reason: 'render_failed',
        })
        expect(fetch).not.toHaveBeenCalled()
        expect(failedRun.result.logs.map(({ level, message }) => [level, message])).toContainEqual([
            'error',
            expect.stringContaining('failed to render: The rendered sandbox email is missing a recipient, subject'),
        ])
    })

    it.each<[string, () => Promise<FetchResponse>]>([
        ['before its headers', () => Promise.reject(new Error('timeout'))],
        [
            'after its headers',
            () =>
                Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.reject(new Error('timeout')),
                    text: () => Promise.reject(new Error('timeout')),
                    dump: () => Promise.resolve(),
                }),
        ],
    ])('reports a test the worker stops answering %s as pending, never as sent', async (_name, respond) => {
        const fetch = jest.fn(respond)

        await expect(tester(fetch).send(testRun())).resolves.toEqual({
            status: 'pending',
            reason: 'sandbox_worker_unreachable',
        })
    })
})
