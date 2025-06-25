import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { buildGlobalsWithInputs, HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../hog-function-templates/hog-function-template-manager.service'
import { HogFlowActionResult } from './types'

type Action = Extract<HogFlowAction, { type: 'function' }>

export class HogFlowActionRunnerFunction {
    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    ) {}

    async run(invocation: CyclotronJobInvocationHogFlow, action: Action): Promise<HogFlowActionResult> {
        // Convert to hog function invocation
        // This mostly involves building a fake hog function

        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(action.config.template_id)

        if (!template) {
            throw new Error(`Template ${action.config.template_id} not found`)
        }

        const hogFunction: HogFunctionType = {
            id: invocation.hogFlow.id, // We use the hog function flow ID
            team_id: invocation.teamId,
            name: `${invocation.hogFlow.name} - ${template.name}`,
            enabled: true,
            type: 'destination',
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            is_addon_required: false,
            created_at: '',
            updated_at: '',
        }

        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.hub.SITE_URL}/project/${teamId}`

        const globals: HogFunctionInvocationGlobals = {
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
            event: invocation.state.event,
            // TODO: Add person info
        }

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: {
                globals: buildGlobalsWithInputs(globals, action.config.inputs),
                timings: [],
            },
        }

        const result = this.hogFunctionExecutor.execute(hogFunctionInvocation)

        // TODO: Swap to `executeWithAsync` or something
        // TODO: Take logs and metrics - modify them to have the correct app_source_id, instance_id as well as pre-pending the logs with the action ID

        logger.info('[HogFlowActionRunnerFunction]', 'Hog function result', {
            finished: result.finished,
            logs: result.logs,
            inputs: hogFunctionInvocation.state.globals.inputs,
        })

        return {
            done: true,
        }
    }
}
