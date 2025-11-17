import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import { AIService } from '../../ai/ai.service'
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

export class AIHandler implements ActionHandler {
    constructor(private aiService: AIService) {}

    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'ai' }>>): Promise<ActionHandlerResult> {
        const { prompt, model } = action.config

        if (!prompt) {
            return {
                error: 'AI step requires a prompt',
                finished: false,
                nextAction: findContinueAction(invocation),
            }
        }

        try {
            // Prepare event data from the workflow state
            const eventData = {
                event: invocation.state.event,
                person: invocation.person,
                variables: invocation.state.variables,
            }

            // Call AI service directly
            const aiResponse = await this.aiService.callAI(prompt, model || 'gpt-4-turbo', eventData)

            // Store result in action output variable if configured
            if (action.output_variable) {
                invocation.state.variables = invocation.state.variables || {}
                invocation.state.variables[action.output_variable.key] = aiResponse || null
            }

            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `AI step completed: ${JSON.stringify(aiResponse)}`,
            })

            return {
                nextAction: findContinueAction(invocation),
                result: aiResponse,
            }
        } catch (error: any) {
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `AI step failed: ${error.message}`,
            })

            return {
                error: error.message,
                finished: false,
                nextAction: findContinueAction(invocation),
            }
        }
    }
}
