import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

import { AgentTaskService } from '../agent-task.service'
import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

// How often a parked agent_task re-checks the task's status while waiting. The subscription matcher
// wakes the job immediately on a $task_run_completed event; this poll is the backstop for a missed
// event, capped so a lost event degrades to slow rather than to a stuck workflow.
const POLL_INTERVAL_SECONDS = 5 * 60

type AgentTaskAction = Extract<HogFlowAction, { type: 'agent_task' }>

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export class AgentTaskHandler implements ActionHandler {
    constructor(private agentTaskService: AgentTaskService) {}

    async execute({ invocation, action }: ActionHandlerOptions<AgentTaskAction>): Promise<ActionHandlerResult> {
        const currentAction = invocation.state.currentAction
        if (!currentAction) {
            throw new Error('agent_task requires a current action')
        }
        const config = action.config
        const taskState = currentAction.agentTaskState

        // Woken by the subscription matcher: the task reached a terminal state.
        if (taskState?.completed) {
            const { status, output } = taskState
            currentAction.agentTaskState = undefined
            return this.advance(invocation, status, output)
        }

        // First entry: kick off the task and park without advancing (mirrors delay/wait_until_condition
        // — advancing eagerly would let the matcher wake us against the following step).
        if (!taskState) {
            const distinctId = invocation.state.event?.distinct_id
            if (!distinctId) {
                throw new Error('agent_task requires a distinct_id to correlate task completion')
            }
            const created = await this.agentTaskService.createAgentTask({
                teamId: invocation.hogFlow.team_id,
                distinctId,
                workflowId: invocation.hogFlow.id,
                workflowRunId: invocation.id,
                actionId: action.id,
                prompt: renderTemplate(config.prompt, invocation),
                title: config.title ? renderTemplate(config.title, invocation) : undefined,
                repository: config.repository,
                createPr: config.create_pr,
            })
            currentAction.agentTaskState = { taskRunId: created.taskRunId }
            return this.park(invocation, config)
        }

        // Woken by the poll cap (the matcher didn't wake us): re-check status directly, and take the
        // timeout edge only once the max wait is genuinely exhausted.
        const status = await this.agentTaskService.getAgentTaskStatus(invocation.hogFlow.team_id, taskState.taskRunId)
        if (TERMINAL_STATUSES.has(status.status)) {
            currentAction.agentTaskState = undefined
            return this.advance(invocation, status.status, status.output)
        }
        return this.park(invocation, config)
    }

    // Success advances down the branch edge (index 0); failure/cancellation down the continue edge.
    private advance(
        invocation: CyclotronJobInvocationHogFlow,
        status: string | undefined,
        output: unknown
    ): ActionHandlerResult {
        if (status === 'completed') {
            return {
                nextAction: findNextAction(invocation.hogFlow, invocation.state.currentAction!.id, 0),
                result: { status, output },
            }
        }
        return {
            nextAction: findContinueAction(invocation),
            result: { status: status ?? 'failed', output },
        }
    }

    private park(invocation: CyclotronJobInvocationHogFlow, config: AgentTaskAction['config']): ActionHandlerResult {
        const scheduledAt = calculatedScheduledAt(
            config.max_wait_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            POLL_INTERVAL_SECONDS
        )
        if (scheduledAt) {
            return { scheduledAt }
        }
        // Max wait elapsed with no terminal status: take the timeout (continue) edge.
        return { nextAction: findContinueAction(invocation), result: { status: 'timed_out' } }
    }
}

// Minimal {{ variable }} interpolation from workflow variables. Pure string replacement (no code
// eval) — enough to thread upstream step results into the prompt without pulling in the hog VM.
function renderTemplate(template: string, invocation: CyclotronJobInvocationHogFlow): string {
    const variables = invocation.state.variables ?? {}
    return template.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (match, key: string) => {
        const value = variables[key]
        if (value === undefined || value === null) {
            return match
        }
        return typeof value === 'string' ? value : JSON.stringify(value)
    })
}
