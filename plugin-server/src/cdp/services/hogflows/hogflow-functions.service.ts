import { HogFunctionType } from '~/cdp/types'
import { HogFlow, HogFlowAction } from '~/schema/hogflow'

import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'

type Action = Extract<HogFlowAction, { type: FunctionActionType }>

// Helper class that can turn a hog flow action into a hog function
export class HogFlowFunctionsService {
    constructor(private hogFunctionTemplateManager: HogFunctionTemplateManagerService) {}

    async buildHogFunction(hogFlow: HogFlow, action: Action): Promise<HogFunctionType> {
        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(action.config.template_id)

        if (!template) {
            throw new Error(`Template '${action.config.template_id}' not found`)
        }

        const hogFunction: HogFunctionType = {
            id: hogFlow.id,
            team_id: hogFlow.team_id,
            name: `${hogFlow.name} - ${template.name}`,
            enabled: true,
            type: template.type,
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            inputs: action.config.inputs,
            inputs_schema: template.inputs_schema,
            created_at: '',
            updated_at: '',
        }

        return hogFunction
    }
}
