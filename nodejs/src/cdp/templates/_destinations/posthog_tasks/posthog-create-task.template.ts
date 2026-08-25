import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-create-task',
    name: 'Create AI task',
    description:
        'Start an AI agent task from a workflow. The agent works in the background and the task shows up in Tasks.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.prompt)) {
  throw Error('Instructions are required')
}

let payload := { 'prompt': inputs.prompt, 'event': event }

if (not empty(inputs.title)) {
  payload.title := inputs.title
}

if (not empty(inputs.model) and not empty(inputs.model.model)) {
  payload.model := inputs.model.model
  if (not empty(inputs.model.reasoning_effort)) {
    payload.reasoning_effort := inputs.model.reasoning_effort
  }
}

if (not empty(inputs.repository)) {
  payload.repository := inputs.repository
}

if (not empty(inputs.connectors)) {
  payload.connectors := inputs.connectors
}

if (not empty(inputs.posthog_mcp_scopes)) {
  payload.posthog_mcp_scopes := inputs.posthog_mcp_scopes
}

if (not empty(inputs.max_parallel_tasks)) {
  payload.max_parallel_tasks := inputs.max_parallel_tasks
}

if (inputs.reply_in_slack_thread != false and event.event == '$slack_message_received' and not empty(event.properties.channel) and not empty(event.properties.ts)) {
  payload.slack_context := {
    'integration_id': event.properties.integration_id,
    'channel': event.properties.channel,
    'thread_ts': event.properties.thread_ts ?? event.properties.ts,
    'message_ts': event.properties.ts,
    'slack_user_id': event.properties.user ?? '',
    'slack_team_id': event.properties.slack_team_id ?? '',
    'is_ext_shared_channel': event.properties.is_ext_shared_channel ?? false
  }
}

let response := postHogCreateTask(payload)

if (response.status == 409) {
  print(f'Task not created: {apiErrorMessage(response)}')
  return { 'skipped': true, 'reason': apiErrorMessage(response) }
}

if (response.status >= 400) {
  throw Error(f'Failed to create task ({response.status}): {apiErrorMessage(response)}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'prompt',
            type: 'string',
            label: 'Instructions',
            secret: false,
            required: true,
            description: 'What the agent should do. Supports variable templating.',
        },
        {
            key: 'title',
            type: 'string',
            label: 'Task title',
            secret: false,
            required: false,
            description: 'Name shown in the task list. Leave empty to name the task from the instructions.',
        },
        {
            key: 'model',
            type: 'task_model',
            label: 'Model',
            secret: false,
            required: false,
            description: 'Model and reasoning effort for the agent. Leave empty to use the default model.',
        },
        {
            key: 'repository',
            type: 'task_repository',
            label: 'Repository',
            secret: false,
            required: false,
            description:
                'GitHub repository the agent works in, e.g. your-org/your-repo. Leave empty for no repository.',
        },
        {
            key: 'connectors',
            type: 'task_mcp_installations',
            label: 'Connectors',
            secret: false,
            required: false,
            description:
                'Connectors from the MCP store the agent can use. Team-shared connections and the workflow creator’s own connections are available.',
        },
        {
            key: 'posthog_mcp_scopes',
            type: 'choice',
            label: 'PostHog access',
            secret: false,
            required: false,
            default: 'read_only',
            choices: [
                { label: 'Read only', value: 'read_only' },
                { label: 'Full access', value: 'full' },
            ],
            description: 'What the agent can do in your PostHog project. Read only blocks changes.',
        },
        {
            key: 'max_parallel_tasks',
            type: 'number',
            label: 'Maximum parallel tasks',
            secret: false,
            required: false,
            default: 5,
            description:
                'New runs are skipped while this many tasks from this workflow are still running. Protects against a burst of trigger events starting too many agents at once.',
        },
        {
            // Only meaningful on a Slack-triggered workflow; the builder hides it for other
            // triggers, and the hog code above no-ops when the trigger event isn't a Slack message.
            key: 'reply_in_slack_thread',
            type: 'boolean',
            label: 'Reply in the Slack thread',
            secret: false,
            required: false,
            default: true,
            templating: false,
            description:
                'The agent posts its updates as replies in the Slack thread that started this workflow. Replies in that thread are sent to the agent.',
        },
        {
            // The engine treats a 4xx as a step failure before the code above runs, unless the
            // status is listed here. 409 is the "task limit reached" reply, which the code turns
            // into a graceful skip.
            key: 'non_failure_status_codes',
            type: 'non_failure_status_codes',
            label: 'Non-failure status codes',
            secret: false,
            required: false,
            hidden: true,
            default: [409],
        },
    ],
}
