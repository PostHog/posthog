import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-run-agent',
    name: 'Run AI agent',
    description: 'Run an AI agent and return its result',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let config := inputs.agent_config

if (empty(config.prompt)) {
    throw Error('Prompt is required')
}

let response := postHogRunAgent({
    'prompt': config.prompt,
    'repository': config.repository,
    'output_schema': config.output_schema
})

if (response.status != 200) {
    let err := response.body.error
    throw Error(f'Agent failed: {err}')
}

let body := response.body

// Surface agent activity logs
let agentLogs := body.logs
if (not empty(agentLogs)) {
    for (let i := 1; i <= length(agentLogs); i := i + 1) {
        print(agentLogs[i])
    }
}

// Log the output
print(f'Agent output: {body.output}')

return body.output
`,
    inputs_schema: [
        {
            key: 'agent_config',
            type: 'agent_config',
            label: 'Agent configuration',
            secret: false,
            required: true,
            default: { prompt: '', github_installation: null, repository: null, output_schema: null },
            description: 'Configure the AI agent prompt, repository, and output schema.',
        },
    ],
}
