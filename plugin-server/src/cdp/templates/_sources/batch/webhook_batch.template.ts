import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'source_webhook',
    id: 'template-source-webhook-batch',
    name: 'Workflows Batch Trigger Webhook',
    description: 'Triggers workflow invocations for a batch of persons',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if(empty(inputs.actor_id)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': {
        'error': '"actor_id" could not be parsed correctly',
      }
    }
  }
}

postHogCapture({
  'event': '$workflow_batch_triggered',
  'distinct_id': inputs.actor_id,
  'properties': { 'filters': inputs.filters }
})
`,
    inputs_schema: [
        {
            key: 'actor_id',
            type: 'string',
            label: 'Actor ID',
            description: 'The actor that triggered this batch workflow run',
            default: '{request.body.actor_id}',
            secret: false,
            required: true,
        },
        {
            key: 'filters',
            type: 'json',
            label: 'Filters',
            description: 'A set of filters to select which persons to trigger the workflow for',
            default: {},
            secret: false,
            required: true,
        },
    ],
}
