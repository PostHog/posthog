import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-claude-managed-agent',
    name: 'Run Claude managed agent',
    description: 'Start a Claude managed agent session and store the session id in a workflow variable.',
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
  throw Error('Environment is required')
}
if (empty(inputs.message)) {
  throw Error('Message is required')
}

let session := claudeCreateSession({
  'api_key': inputs.anthropic_workspace.api_key,
  'agent': inputs.agent,
  'environment_id': inputs.environment,
  'vault_ids': inputs.vault_id ? [inputs.vault_id] : [],
  'message': inputs.message
})

if (session.status < 200 or session.status >= 300) {
  throw Error(f'Failed to create Claude session: {session.status} {session.body}')
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
            requiredScopes: 'placeholder',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'agent',
            type: 'integration_field',
            integration_key: 'anthropic_workspace',
            integration_field: 'anthropic_agent',
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
            integration_field: 'anthropic_environment',
            label: 'Environment',
            description: 'Execution environment for the agent.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'vault_id',
            type: 'integration_field',
            integration_key: 'anthropic_workspace',
            integration_field: 'anthropic_vault',
            label: 'Vault',
            description: 'Vault containing secrets the agent can read. Optional.',
            secret: false,
            hidden: false,
            required: false,
        },
        {
            key: 'message',
            type: 'string',
            label: 'Initial message',
            description:
                'First message sent to the agent. Liquid templates with event/person properties are supported.',
            secret: false,
            hidden: false,
            required: true,
        },
    ],
}
