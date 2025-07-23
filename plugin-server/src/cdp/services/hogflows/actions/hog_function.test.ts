// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { compileHog } from '~/cdp/templates/compiler'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { findActionByType } from '../hogflow-utils'
import { HogFunctionHandler } from './hog_function'

describe('HogFunctionHandler', () => {
    let hub: Hub
    let team: Team
    let hogFunctionHandler: HogFunctionHandler
    let mockHogFunctionExecutor: HogExecutorService
    let mockHogFunctionTemplateManager: HogFunctionTemplateManagerService

    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'function' }>

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        mockHogFunctionExecutor = new HogExecutorService(hub)
        mockHogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub)
        hogFunctionHandler = new HogFunctionHandler(hub, mockHogFunctionExecutor, mockHogFunctionTemplateManager)

        // Simple hog function that prints the inputs
        const exampleHog = `fetch('http://localhost/test', { 'method': 'POST', 'body': inputs })`

        const template = await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            hog: exampleHog,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
                {
                    key: 'slack',
                    type: 'integration',
                    required: true,
                },
            ],
            bytecode: await compileHog(exampleHog),
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
                                slack: {
                                    value: 1,
                                },
                            },
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

        const handlerResult = await hogFunctionHandler.execute(invocation, action, invocationResult)

        expect(mockFetch.mock.calls).toMatchInlineSnapshot(`
            [
              [
                "http://localhost/test",
                {
                  "body": "{"name":"John Doe","slack":{"team":"foobar","access_token":"token","not_encrypted":"not-encrypted"}}",
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                  "timeoutMs": 10000,
                },
              ],
            ]
        `)

        expect(handlerResult.nextAction?.id).toBe('exit')
        expect(invocationResult.logs).toHaveLength(1)
        expect(invocationResult.logs[0].message).toContain('[Action:function] Function completed')
    })

    it('should throw an error if template is not found', async () => {
        const action = findActionByType(invocation.hogFlow, 'function')!
        action.config.template_id = 'template_123'

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await expect(hogFunctionHandler.execute(invocation, action, invocationResult)).rejects.toThrow(
            "Template 'template_123' not found"
        )
    })
})
