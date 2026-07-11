import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { logger, serializeError } from '~/common/utils/logger'

import { AgentTaskService } from '../agent-task.service'
import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

// How often a parked agent_task re-checks the task's status while waiting. The subscription matcher
// wakes the job immediately on a $task_run_completed event; this poll is the backstop for a missed
// event, capped so a lost event degrades to slow rather than to a stuck workflow.
const POLL_INTERVAL_SECONDS = 5 * 60

// Interpolated workflow variables can carry event-derived (end-user-controlled) data; cap each value
// so an attacker-inflated event property can't balloon the prompt handed to the coding agent.
const MAX_INTERPOLATED_VALUE_LENGTH = 2000

// Task output feeds workflow variables (5KB total cap) and the customer-visible step result; cap the
// serialized size here so an oversized agent output degrades to a truncation marker instead of
// failing the step after the task already succeeded.
const MAX_OUTPUT_BYTES = 4096

// Terminal statuses discovered by the poll backstop rather than the subscription-matcher wake — the
// signal that the event pipeline missed a wake (mirrors cdp_hogflow_wait_poll_only_advance).
export const counterAgentTaskPollAdvance = new Counter({
    name: 'cdp_hogflow_agent_task_poll_advance',
    help: 'agent_task advanced via the polling backstop, not the subscription matcher wake.',
})

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
                throw new Error(
                    'Agent task step needs a triggering event with a distinct ID to receive the task result'
                )
            }
            const created = await this.agentTaskService.createAgentTask({
                teamId: invocation.hogFlow.team_id,
                distinctId,
                workflowId: invocation.hogFlow.id,
                workflowRunId: invocation.id,
                actionId: action.id,
                prompt: renderTemplate(config.prompt, invocation),
                title: config.title ? renderTemplate(config.title, invocation) : action.name,
                repository: config.repository,
                createPr: config.create_pr,
            })
            currentAction.agentTaskState = { taskRunId: created.taskRunId }
            return this.park(invocation, config)
        }

        // Woken by the poll cap (the matcher didn't wake us): re-check status directly, and take the
        // timeout edge only once the max wait is genuinely exhausted. The poll is a best-effort
        // backstop — a transient failure re-parks rather than failing a healthy run; persistent
        // failure resolves via the max_wait timeout edge.
        let status
        try {
            status = await this.agentTaskService.getAgentTaskStatus(invocation.hogFlow.team_id, taskState.taskRunId)
        } catch (error) {
            logger.warn('agent_task status poll failed; re-parking', {
                taskRunId: taskState.taskRunId,
                teamId: invocation.hogFlow.team_id,
                error: serializeError(error),
            })
            return this.park(invocation, config)
        }
        if (TERMINAL_STATUSES.has(status.status)) {
            counterAgentTaskPollAdvance.inc()
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
        const cappedOutput = capOutput(output)
        if (status === 'completed') {
            return {
                nextAction: findNextAction(invocation.hogFlow, invocation.state.currentAction!.id, 0),
                result: { status, output: cappedOutput },
            }
        }
        return {
            nextAction: findContinueAction(invocation),
            result: { status: status ?? 'failed', output: cappedOutput },
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
        // Max wait elapsed with no terminal status: take the timeout (continue) edge. The task itself
        // keeps running and may still finish later; its completion event will wake nothing.
        return { nextAction: findContinueAction(invocation), result: { status: 'timed_out' } }
    }
}

// Keep the step result (and anything stored into output_variable) under the workflow variables cap.
function capOutput(output: unknown): unknown {
    if (output === undefined || output === null) {
        return output
    }
    const serialized = JSON.stringify(output)
    if (Buffer.byteLength(serialized, 'utf8') <= MAX_OUTPUT_BYTES) {
        return output
    }
    return { truncated: true, preview: serialized.slice(0, 1000) }
}

// Minimal {{ variable }} interpolation from workflow variables. Pure string replacement (no code
// eval) — enough to thread upstream step results into the prompt without pulling in the hog VM.
// Values are length-capped: variables can carry event-derived, end-user-controlled data, and this
// string is the prompt of an autonomous coding agent.
function renderTemplate(template: string, invocation: CyclotronJobInvocationHogFlow): string {
    const variables = invocation.state.variables ?? {}
    return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, key: string) => {
        const value = variables[key]
        if (value === undefined || value === null) {
            return match
        }
        const rendered = typeof value === 'string' ? value : JSON.stringify(value)
        return rendered.slice(0, MAX_INTERPOLATED_VALUE_LENGTH)
    })
}
