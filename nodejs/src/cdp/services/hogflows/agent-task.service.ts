import { parseJSON } from '~/common/utils/json-parse'
import { logger, serializeError } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

// Dedicated header for the agent_task Node -> Django hop. Paired with WORKFLOWS_TASKS_API_SECRET,
// scoped to this one caller/callee pair rather than the fleet-wide INTERNAL_API_SECRET.
export const WORKFLOWS_TASKS_SECRET_HEADER = 'X-Workflows-Tasks-Secret'

export interface CreateAgentTaskRequest {
    teamId: number
    // Correlation identity: the task-completion internal event is emitted with this distinct_id so
    // the subscription matcher finds this parked job. Matched jobs are then disambiguated by taskRunId.
    distinctId: string
    workflowId: string
    workflowRunId: string
    actionId: string
    prompt: string
    title?: string
    repository?: string
    createPr?: boolean
}

export interface CreateAgentTaskResponse {
    taskRunId: string
    status: string
}

export interface AgentTaskStatusResponse {
    status: string
    output: unknown
    errorMessage: string | null
}

/**
 * Talks to the tasks product (via a Django internal endpoint) to start a PostHog Code task for a
 * workflow agent_task step and to poll its status as a backstop when the completion event is missed.
 */
export class AgentTaskService {
    constructor(
        private internalApiBaseUrl: string,
        private secret: string
    ) {}

    async createAgentTask(request: CreateAgentTaskRequest): Promise<CreateAgentTaskResponse> {
        const urlPath = `/api/projects/${request.teamId}/internal/workflows/agent_tasks`
        const response = await this.fetch(urlPath, {
            method: 'POST',
            // Creation writes rows and dispatches a Temporal workflow before responding — give it
            // more than the 3s default so a slow dispatch doesn't orphan a created-but-unacked task.
            timeoutMs: 30_000,
            body: JSON.stringify({
                distinct_id: request.distinctId,
                workflow_id: request.workflowId,
                workflow_run_id: request.workflowRunId,
                action_id: request.actionId,
                prompt: request.prompt,
                title: request.title,
                repository: request.repository,
                create_pr: request.createPr,
            }),
        })
        const data = parseJSON(response) as { task_run_id: string; status: string }
        return { taskRunId: data.task_run_id, status: data.status }
    }

    async getAgentTaskStatus(teamId: number, taskRunId: string): Promise<AgentTaskStatusResponse> {
        const urlPath = `/api/projects/${teamId}/internal/workflows/agent_tasks/${taskRunId}`
        const response = await this.fetch(urlPath, { method: 'GET' })
        const data = parseJSON(response) as { status: string; output: unknown; error_message: string | null }
        return { status: data.status, output: data.output, errorMessage: data.error_message ?? null }
    }

    private async fetch(
        urlPath: string,
        params: { method: string; body?: string; timeoutMs?: number }
    ): Promise<string> {
        // Fail fast on a wiring mistake rather than burning timeouts against localhost in prod.
        if (!this.internalApiBaseUrl || !this.secret) {
            throw new Error('Agent task service is not configured (INTERNAL_API_BASE_URL / WORKFLOWS_TASKS_API_SECRET)')
        }
        const url = `${this.internalApiBaseUrl}${urlPath}`
        try {
            const response = await internalFetch(url, {
                method: params.method,
                body: params.body,
                timeoutMs: params.timeoutMs,
                headers: {
                    'Content-Type': 'application/json',
                    [WORKFLOWS_TASKS_SECRET_HEADER.toLowerCase()]: this.secret,
                },
            })
            if (response.status < 200 || response.status >= 300) {
                const errorText = await response.text()
                throw new Error(`Agent task request failed: ${response.status} ${errorText}`)
            }
            return await response.text()
        } catch (error) {
            logger.error('Error calling agent task endpoint', { error: serializeError(error), urlPath })
            throw error
        }
    }
}
