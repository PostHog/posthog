import { HogFunctionTemplateCompiled } from '~/cdp/types'

export const template: HogFunctionTemplateCompiled = {
    free: false,
    status: 'alpha',
    type: 'warehouse_source_webhook',
    id: 'template-warehouse-source-default',
    name: 'Default warehouse source webhook',
    description: 'Passthrough webhook that returns the request body as-is',
    icon_url: '/static/services/webhook.png',
    category: ['Data warehouse'],
    code_language: 'hog',
    code: `
return request.body
  `,
    bytecode: ['_H', 1, 32, 'body', 32, 'request', 1, 2, 38],
    inputs_schema: [],
}
