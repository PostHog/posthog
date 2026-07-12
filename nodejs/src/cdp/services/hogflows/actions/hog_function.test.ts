import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { CyclotronJobInvocationHogFlow, DBHogFunctionTemplate } from '../../../types'
import { HogExecutorService } from '../../hog-executor.service'
import { HogInputsService } from '../../hog-inputs.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { TeamWorkflowsConfigService } from '../../managers/team-workflows-config.service'
import { EmailValidationService } from '../../messaging/email-validation.service'
import { EmailService } from '../../messaging/email.service'
import { EmailTrackingCodeSigner } from '../../messaging/helpers/tracking-code'
import { RecipientPreferencesService } from '../../messaging/recipient-preferences.service'
import { RecipientTokensService } from '../../messaging/recipient-tokens.service'
import { HogFlowFunctionsService } from '../hogflow-functions.service'
import { findActionByType } from '../hogflow-utils'
import { HogFunctionHandler } from './hog_function'

describe('HogFunctionHandler', () => {
    let hub: Hub
    let team: Team
    let hogFunctionHandler: HogFunctionHandler
    let mockHogFunctionExecutor: HogExecutorService
    let mockHogFunctionTemplateManager: HogFunctionTemplateManagerService
    let mockHogFlowFunctionsService: HogFlowFunctionsService
    let mockRecipientPreferencesService: RecipientPreferencesService
    let mockEmailValidationService: EmailValidationService

    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'function' }>
    let template: DBHogFunctionTemplate

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub.postgres)

        const hogInputsService = new HogInputsService(hub.integrationManager, hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const emailService = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL)
        )
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        mockHogFunctionExecutor = new HogExecutorService(
            {
                hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
                fetchRetries: hub.CDP_FETCH_RETRIES,
                fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
                fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
            },
            { teamManager: hub.teamManager, siteUrl: hub.SITE_URL },
            hogInputsService,
            emailService,
            recipientTokensService
        )
        mockHogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub.postgres)
        mockHogFlowFunctionsService = new HogFlowFunctionsService(
            hub.SITE_URL,
            mockHogFunctionTemplateManager,
            mockHogFunctionExecutor
        )
        mockRecipientPreferencesService = {
            shouldSkipAction: jest.fn().mockResolvedValue(false),
        } as any
        mockEmailValidationService = {
            getSkipReason: jest.fn().mockResolvedValue(null),
        } as any
        hogFunctionHandler = new HogFunctionHandler(
            mockHogFlowFunctionsService,
            mockRecipientPreferencesService,
            mockEmailValidationService,
            'fetch'
        )

        // Simple hog function that prints the inputs

        template = await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            code: `fetch('http://localhost/test', { 'method': 'POST', 'body': inputs })`,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
                {
                    key: 'oauth',
                    type: 'integration',
                    required: true,
                },
            ],
        })

        await insertIntegration(hub.postgres, team.id, {
            id: 1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withWorkflow({
                actions: {
                    function: {
                        type: 'function',
                        config: {
                            template_id: template.template_id,
                            inputs: {
                                name: {
                                    value: 'John Doe',
                                },
                                oauth: {
                                    value: 1,
                                },
                            },
                            mappings: [
                                {
                                    name: 'input mapping field',
                                },
                            ],
                        },
                    },
                    exit: {
                        type: 'exit',
                        config: {},
                    },
                },
                edges: [
                    {
                        from: 'function',
                        to: 'exit',
                        type: 'continue',
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'function')!
        invocation = createExampleHogFlowInvocation(hogFlow)

        invocation.state.currentAction = {
            id: action.id,
            startedAtTimestamp: DateTime.utc().toMillis(),
        }
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('should execute a hog function with integration inputs and continue', async () => {
        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        const handlerResult = await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        expect(mockFetch.mock.calls).toMatchInlineSnapshot(`
            [
              [
                "http://localhost/test",
                {
                  "body": "{"name":"John Doe","oauth":{"team":"foobar","access_token":"token","not_encrypted":"not-encrypted","access_token_raw":"token"}}",
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                },
              ],
            ]
        `)

        expect(handlerResult.nextAction?.id).toBe('exit')
        expect(invocationResult.logs).toHaveLength(1)
        expect(invocationResult.logs[0].message).toContain('[Action:function] Function completed')
    })

    describe('with groups', () => {
        beforeEach(() => {
            invocation.groups = {
                organization: {
                    id: 'org_key',
                    type: 'organization',
                    index: 0,
                    url: '',
                    properties: { owner_name: 'Chris McNeill' },
                },
            }
        })

        it('should forward groups to the hog function invocation globals', async () => {
            const buildHogFunctionInvocationSpy = jest.spyOn(mockHogFlowFunctionsService, 'buildHogFunctionInvocation')

            const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
                queue: 'hog',
                queuePriority: 0,
            })

            await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

            const passedGlobals = buildHogFunctionInvocationSpy.mock.calls[0][2]
            expect(passedGlobals.groups).toEqual(invocation.groups)
        })

        it('should render a group property referenced in a function input template', async () => {
            // {groups.organization.properties.owner_name} compiled to hog bytecode
            action.config.inputs.name = {
                value: '{groups.organization.properties.owner_name}',
                templating: 'hog',
                bytecode: ['_H', 1, 32, 'owner_name', 32, 'properties', 32, 'organization', 32, 'groups', 1, 4],
            }

            const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
                queue: 'hog',
                queuePriority: 0,
            })

            const handlerResult = await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

            expect(handlerResult.error).toBeUndefined()
            expect(mockFetch.mock.calls[0][1].body).toContain('"name":"Chris McNeill"')
        })
    })

    it('should throw an error if template is not found', async () => {
        const action = findActionByType(invocation.hogFlow, 'function')!
        action.config.template_id = 'template_123'

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await expect(hogFunctionHandler.execute({ invocation, action, result: invocationResult })).rejects.toThrow(
            "Template 'template_123' not found"
        )
    })

    it('should check recipient preferences before execution', async () => {
        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const callArgs = (mockRecipientPreferencesService.shouldSkipAction as jest.Mock).mock.calls[0]
        expect(callArgs[0]).toBeTruthy()
        expect(callArgs[1]).toBe(action)
    })

    it('should pass proper inputs to buildHogFunctionInvocation', async () => {
        const buildHogFunctionInvocationSpy = jest.spyOn(mockHogFlowFunctionsService, 'buildHogFunctionInvocation')

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const calledConfig = buildHogFunctionInvocationSpy.mock.calls[0][1]
        expect(calledConfig.inputs).toEqual({
            name: {
                value: 'John Doe',
            },
            oauth: {
                value: 1,
            },
        })
        expect(calledConfig.inputs_schema).toEqual([
            {
                key: 'name',
                type: 'string',
                required: true,
            },
            {
                key: 'oauth',
                type: 'integration',
                required: true,
            },
        ])
        expect(calledConfig.template_id).toEqual(template.template_id)
        expect(calledConfig.mappings).toEqual([{ name: 'input mapping field' }])
    })

    it('should skip execution if recipient preferences service returns true', async () => {
        ;(mockRecipientPreferencesService.shouldSkipAction as jest.Mock).mockResolvedValueOnce(true)

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        const handlerResult = await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const callArgs = (mockRecipientPreferencesService.shouldSkipAction as jest.Mock).mock.calls[0]
        expect(callArgs[0]).toBeTruthy()
        expect(callArgs[1]).toBe(action)
        expect(handlerResult.nextAction?.id).toBe('exit')
        expect(invocationResult.logs).toHaveLength(1)
        expect(invocationResult.logs[0].message).toContain(
            `[Action:function] Recipient has opted out, skipping message delivery.`
        )
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('should skip the send and emit email_bounce_prevented when validation predicts a hard bounce', async () => {
        ;(mockEmailValidationService.getSkipReason as jest.Mock).mockResolvedValueOnce(
            'Skipping send: the domain "dead.invalid" has no reachable mail servers, so this message would hard bounce.'
        )

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        const handlerResult = await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        // Flow continues to the next action (a skip, not a failure branch), and nothing was sent.
        expect(handlerResult.nextAction?.id).toBe('exit')
        expect(mockFetch).not.toHaveBeenCalled()
        expect(invocationResult.logs[0].message).toContain('no reachable mail servers')
        expect(invocationResult.metrics).toEqual([
            {
                team_id: team.id,
                app_source_id: invocation.functionId,
                instance_id: action.id,
                metric_kind: 'email',
                metric_name: 'email_bounce_prevented',
                count: 1,
            },
        ])
    })

    it('should emit a single billable_invocation metric upon function completion', async () => {
        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const billableMetrics = invocationResult.metrics.filter(
            (metric) => metric.metric_name === 'billable_invocation' && metric.metric_kind === 'fetch'
        )

        expect(billableMetrics).toHaveLength(1)

        expect(billableMetrics[0]).toMatchObject({
            team_id: team.id,
            app_source_id: invocation.functionId,
            instance_id: action.id,
            metric_kind: 'fetch',
            metric_name: 'billable_invocation',
            count: 1,
        })
    })

    it('should emit a billable_invocation metric with email kind when billingMetricType is email', async () => {
        hogFunctionHandler = new HogFunctionHandler(
            mockHogFlowFunctionsService,
            mockRecipientPreferencesService,
            mockEmailValidationService,
            'email'
        )

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const billableMetrics = invocationResult.metrics.filter(
            (metric) => metric.metric_name === 'billable_invocation' && metric.metric_kind === 'email'
        )

        expect(billableMetrics).toHaveLength(1)

        expect(billableMetrics[0]).toMatchObject({
            team_id: team.id,
            app_source_id: invocation.functionId,
            instance_id: action.id,
            metric_kind: 'email',
            metric_name: 'billable_invocation',
            count: 1,
        })
    })

    it('should not emit a billable_invocation metric if function is not finished', async () => {
        // Mock the executeWithAsyncFunctions to return a non-finished result
        jest.spyOn(mockHogFlowFunctionsService, 'executeWithAsyncFunctions').mockResolvedValueOnce({
            finished: false,
            invocation: invocation as any,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
            emailAssets: [],
        })

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const billableMetrics = invocationResult.metrics.filter(
            (metric) => metric.metric_name === 'billable_invocation' && metric.metric_kind === 'fetch'
        )

        expect(billableMetrics).toHaveLength(0)
    })

    it('should not emit a billable_invocation metric when recipient opts out', async () => {
        ;(mockRecipientPreferencesService.shouldSkipAction as jest.Mock).mockResolvedValueOnce(true)

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await hogFunctionHandler.execute({ invocation, action, result: invocationResult })

        const billableMetrics = invocationResult.metrics.filter(
            (metric) => metric.metric_name === 'billable_invocation'
        )

        // Ensure NO billing metrics are emitted when recipient has opted out
        expect(billableMetrics).toHaveLength(0)

        // Verify the function was still marked as finished with the right log
        expect(invocationResult.logs).toHaveLength(1)
        expect(invocationResult.logs[0].message).toContain('Recipient has opted out')
    })

    describe('non_failure_status_codes propagation', () => {
        it('propagates non_failure_status_codes from action.config.inputs into the synthetic hog function', async () => {
            const templateWithNonFailure = await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-test-hogflow-non-failure-status',
                name: 'Test Template With Non-Failure Codes',
                code: `fetch('http://localhost/test', { 'method': 'POST', 'body': {} })`,
                inputs_schema: [
                    {
                        key: 'non_failure_status_codes',
                        type: 'non_failure_status_codes',
                        required: false,
                    },
                ],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withWorkflow({
                    actions: {
                        function: {
                            type: 'function',
                            config: {
                                template_id: templateWithNonFailure.template_id,
                                inputs: {
                                    non_failure_status_codes: {
                                        value: ['4xx', 500],
                                    },
                                },
                            },
                        },
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [{ from: 'function', to: 'exit', type: 'continue' }],
                })
                .build()

            const flowAction = findActionByType(hogFlow, 'function')!

            const builtHogFunction = await mockHogFlowFunctionsService.buildHogFunction(hogFlow, flowAction.config)

            expect(builtHogFunction.inputs_schema).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        key: 'non_failure_status_codes',
                        type: 'non_failure_status_codes',
                    }),
                ])
            )
            expect(builtHogFunction.inputs?.non_failure_status_codes).toEqual({
                value: ['4xx', 500],
            })
        })
    })
})
