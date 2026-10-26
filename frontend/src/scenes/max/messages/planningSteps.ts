import { PlanningStep, PlanningStepStatus } from '~/queries/schema/schema-assistant-messages'

import { EnhancedToolCall } from '../max-constants'

export const PLAN_STEP_STATUS: Record<string, 'pending' | 'active' | 'done' | 'failed'> = {
    completed: 'done',
    in_progress: 'active',
    failed: 'failed',
}

/** The steps of a `todo_write` call, whose `todos` arg holds `{ content, status, activeForm }` items. */
export function parsePlanningSteps(toolCall: EnhancedToolCall): PlanningStep[] {
    if (!Array.isArray(toolCall.args.todos)) {
        return []
    }
    return (toolCall.args.todos as Array<{ content: string; status: string; activeForm: string }>).map((todo) => ({
        description: todo.content,
        status: todo.status as PlanningStepStatus,
    }))
}
