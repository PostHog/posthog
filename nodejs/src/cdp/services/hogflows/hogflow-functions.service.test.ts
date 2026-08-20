import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'

import { HogExecutorAsyncService } from '../hog-executor-async.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { HogFlowFunctionsService } from './hogflow-functions.service'

describe('HogFlowFunctionsService', () => {
    it('carries the action config and the flow trigger type into hog function metadata', async () => {
        const templateManager = {
            getHogFunctionTemplate: jest.fn().mockResolvedValue({
                template_id: 'template-email',
                name: 'Email',
                type: 'destination',
                bytecode: [],
                inputs_schema: [],
            }),
        } as unknown as HogFunctionTemplateManagerService
        const service = new HogFlowFunctionsService(
            'http://localhost',
            templateManager,
            {} as unknown as HogExecutorAsyncService
        )
        const hogFlow = new FixtureHogFlowBuilder()
            .withSimpleWorkflow({ trigger: { type: 'batch', filters: {} } as any })
            .build()

        const hogFunction = await service.buildHogFunction(hogFlow, {
            template_id: 'template-email',
            message_category_type: 'marketing',
            inputs: {},
        } as any)

        expect(hogFunction.metadata).toMatchObject({
            message_category_type: 'marketing',
            trigger_type: 'batch',
        })
        expect(hogFunction.metadata?.inputs).toBeUndefined()
    })
})
