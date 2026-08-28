import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation_log',
    id: 'template-log-transformation-default',
    name: 'Custom log transformation',
    description: 'Start from scratch. Mutate the log record and return it, or return null to drop it.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Runs on every log record for your project.
//
// 'record' fields you can change: body, attributes, resource_attributes, severity_text
// 'record' fields that are read-only: severity_number, service_name, instrumentation_scope,
//          event_name, timestamp, observed_timestamp, trace_id, span_id
//
// Return the record to keep it (optionally mutated), or return null to drop it.
// Note: severity_text is lowercased before this runs — compare against 'error', 'info', etc.

return record
`,
    inputs_schema: [],
}
