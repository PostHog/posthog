import { NativeTemplate } from '~/cdp/types'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { defaultConfig } from '~/common/config/config'

let scopedJwt: ScopedServiceJwt | null = null

function tasksCreateJwt(): ScopedServiceJwt {
    if (!scopedJwt) {
        scopedJwt = new ScopedServiceJwt(PosthogJwtAudience.TASKS_CREATE, defaultConfig.TASKS_CREATE_JWT_SECRET)
    }
    return scopedJwt
}

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-posthog-create-task',
    name: 'Create task',
    description: 'Start an agent task from this workflow, optionally reporting back into a Slack thread',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    perform: async (request, { payload, teamId, hogFunctionId, siteUrl }) => {
        const prompt = typeof payload.prompt === 'string' ? payload.prompt.trim() : ''
        if (!prompt) {
            throw new Error('Instructions are required')
        }

        const jwt = tasksCreateJwt()
        if (!jwt.enabled) {
            throw new Error('Creating tasks is not configured in this environment.')
        }

        const body: Record<string, any> = { hog_flow_id: hogFunctionId, prompt }
        if (payload.title) {
            body.title = payload.title
        }
        if (payload.repository) {
            body.repository = payload.repository
        }
        if (payload.max_parallel_tasks) {
            body.max_parallel_tasks = payload.max_parallel_tasks
        }
        if (payload.model?.model) {
            body.model = payload.model.model
            if (payload.model.reasoning_effort) {
                body.reasoning_effort = payload.model.reasoning_effort
            }
        }
        if (payload.connectors?.length) {
            body.connectors = payload.connectors
        }
        if (payload.slack_channel && payload.slack_thread_ts) {
            body.context = {
                type: 'slack',
                channel: payload.slack_channel,
                thread_ts: payload.slack_thread_ts,
                slack_user_id: payload.slack_user_id ?? '',
                slack_team_id: payload.slack_team_id ?? '',
            }
        }

        const response = await request(`${siteUrl}/api/projects/${teamId}/workflow_tasks/`, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${jwt.mint({ team_id: teamId, hog_flow_id: hogFunctionId })}`,
            },
            json: body,
            throwHttpErrors: false,
        })

        if (response.status === 409) {
            return { skipped: true, reason: response.data?.detail ?? 'Workflow already has its maximum tasks running' }
        }
        if (response.status >= 400) {
            throw new Error(`Failed to create task (${response.status}): ${response.data?.detail ?? response.content}`)
        }
        return response.data
    },
    inputs_schema: [
        {
            key: 'prompt',
            type: 'string',
            label: 'Instructions',
            secret: false,
            required: true,
            description: 'What the agent should do. Templatable, e.g. {event.properties.text}.',
        },
        {
            key: 'title',
            type: 'string',
            label: 'Title',
            secret: false,
            required: false,
            description: 'Defaults to the start of the instructions.',
        },
        {
            key: 'repository',
            type: 'task_repository',
            label: 'Repository',
            secret: false,
            required: false,
            description: 'Leave empty for a task with no code access.',
        },
        {
            key: 'model',
            type: 'task_model',
            label: 'Model',
            secret: false,
            required: false,
            description: 'Leave empty to use the project default.',
        },
        {
            key: 'connectors',
            type: 'task_mcp_installations',
            label: 'MCP connectors',
            secret: false,
            required: false,
            description: 'Shared MCP servers the agent may use.',
        },
        {
            key: 'max_parallel_tasks',
            type: 'number',
            label: 'Maximum tasks in flight',
            secret: false,
            required: false,
            default: 5,
            description: 'Skip creating a task while this workflow already has this many running.',
        },
        {
            key: 'slack_channel',
            type: 'string',
            label: 'Slack channel',
            secret: false,
            required: false,
            default: '{event.properties.channel}',
            description: 'Set with a thread timestamp to have the task report back into Slack.',
        },
        {
            key: 'slack_thread_ts',
            type: 'string',
            label: 'Slack thread',
            secret: false,
            required: false,
            default: '{event.properties.ts}',
            description: 'Timestamp of the message to reply under.',
        },
        {
            key: 'slack_user_id',
            type: 'string',
            label: 'Slack user',
            secret: false,
            required: false,
            default: '{event.properties.user}',
            description: 'Who triggered the workflow, so the task can tag them.',
        },
    ],
}
