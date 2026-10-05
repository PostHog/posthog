import { HogFunctionTemplate } from '~/cdp/types'

import { HTTP_LOG_SOURCE_HOG_CODE, httpLogSourceInputsSchema } from './shared'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-http-server-logs',
    name: 'HTTP server logs',
    description:
        'Capture server-side HTTP request logs as $http_log events, from any server, proxy, or edge function. Powers bot analytics: crawlers and AI agents rarely execute JavaScript, so they only show up in server logs.',
    icon_url: '/static/services/webhook.svg',
    category: ['Infrastructure', 'Monitoring'],
    code_language: 'hog',
    code: HTTP_LOG_SOURCE_HOG_CODE,
    inputs_schema: httpLogSourceInputsSchema({
        authHeaderDescription: `If set, the incoming Authorization header must match this value exactly, e.g. "Bearer SECRET_TOKEN". Set one in production: this endpoint accepts events for your project from anyone who knows the URL.

POST one JSON object per request (one request emits one $http_log event):

\`\`\`json
{
    "url": "https://example.com/pricing?utm_source=newsletter",
    "method": "GET",
    "status_code": 200,
    "ip": "203.0.113.7",
    "user_agent": "Mozilla/5.0 ...",
    "referrer": "https://www.google.com/",
    "timestamp": 1755600000000,
    "properties": { "region": "iad1" }
}
\`\`\`

Only \`url\` (or \`host\`) is required. Include \`user_agent\` so PostHog can classify bot traffic, and \`ip\` for GeoIP. Extra fields under \`properties\` are passed through to the event.`,
    }),
}
