import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'destination',
    id: 'template-claude-managed-agent',
    name: 'Claude managed agent',
    description: 'Start a Claude managed agent session and send the initial user message to kick it off.',
    icon_url: '/static/services/anthropic.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.anthropic_workspace.api_key)) {
  throw Error('Anthropic API key is missing from the configured workspace integration')
}
if (empty(inputs.agent)) {
  throw Error('Agent is required')
}
if (empty(inputs.environment)) {
  throw Error('Agent environment is required')
}
if (empty(inputs.message)) {
  throw Error('Initial message is required')
}

let session := claudeCreateSession({
  'api_key': inputs.anthropic_workspace.api_key,
  'agent': inputs.agent,
  'environment_id': inputs.environment,
  'vault_ids': inputs.vault_id ? [inputs.vault_id] : []
})

if (session.status < 200 or session.status >= 300) {
  let bodyStr := f'{session.body}'
  if (length(bodyStr) > 500) {
    bodyStr := concat(substring(bodyStr, 1, 500), '...')
  }
  throw Error(f'Failed to create Claude session: {session.status} {bodyStr}')
}

let firstMessage := claudeSendUserMessage({
  'api_key': inputs.anthropic_workspace.api_key,
  'session_id': session.body.id,
  'text': inputs.message
})

if (firstMessage.status < 200 or firstMessage.status >= 300) {
  // Session was created but the initial message failed to send. Best-effort cancel
  // the orphaned session so the customer is not billed for an idle agent. We don't
  // block the throw on cancel success — the original failure is what matters.
  let cancel := claudeCancelSession({
    'api_key': inputs.anthropic_workspace.api_key,
    'session_id': session.body.id
  })
  let bodyStr := f'{firstMessage.body}'
  if (length(bodyStr) > 500) {
    bodyStr := concat(substring(bodyStr, 1, 500), '...')
  }
  throw Error(f'Created Claude session {session.body.id} but failed to send initial message: {firstMessage.status} {bodyStr} (cancel attempt: {cancel.status})')
}

return {
  'id': session.body.id,
  'status': session.body.status,
  'environment_id': session.body.environment_id,
  'agent': session.body.agent
}
`,
    inputs_schema: [
        {
            key: 'anthropic_workspace',
            type: 'integration',
            integration: 'anthropic',
            label: 'Anthropic workspace',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'agent',
            type: 'integration_field',
            integration_key: 'anthropic_workspace',
            integration_field: 'anthropic_managed_agent',
            label: 'Agent',
            description: 'Claude managed agent to run.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'environment',
            type: 'integration_field',
            integration_key: 'anthropic_workspace',
            integration_field: 'anthropic_managed_agent_environment',
            label: 'Agent environment',
            description: 'Execution environment for the agent.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'vault_id',
            type: 'integration_field',
            integration_key: 'anthropic_workspace',
            integration_field: 'anthropic_managed_agent_vault',
            label: 'Secrets vault',
            description: 'Vault containing secrets the agent can read.',
            secret: false,
            hidden: false,
            required: false,
        },
        {
            key: 'message',
            type: 'string',
            label: 'Initial message',
            description:
                'First message sent to the agent. Hog template expressions like `{event.properties.message}` are supported.',
            templating: 'hog',
            secret: false,
            hidden: false,
            required: true,
        },
    ],
}
