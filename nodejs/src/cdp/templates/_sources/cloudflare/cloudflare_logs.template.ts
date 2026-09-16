import { HogFunctionTemplate } from '~/cdp/types'

import { HTTP_LOG_SOURCE_HOG_CODE, httpLogSourceInputsSchema } from '../http_logs/shared'

// A copy-paste Worker, not Logpush: Logpush requires an Enterprise plan and delivers
// gzipped NDJSON batches of up to 1000 records, while source webhooks emit a single
// event per invocation. A Worker runs on every Cloudflare plan and sends one request
// per log record, so nothing is dropped.
const WORKER_SNIPPET = `\`\`\`js
export default {
    async fetch(request, env, ctx) {
        const response = await fetch(request)
        ctx.waitUntil(track(request, response, env).catch(() => {}))
        return response
    },
}

async function track(request, response, env) {
    await fetch(env.POSTHOG_ENDPOINT, {
        method: 'POST',
        headers: {
            'content-type': 'application/json',
            authorization: \`Bearer \${env.POSTHOG_SECRET}\`,
        },
        body: JSON.stringify({
            url: request.url,
            method: request.method,
            status_code: response.status,
            ip: request.headers.get('cf-connecting-ip'),
            user_agent: request.headers.get('user-agent'),
            referrer: request.headers.get('referer'),
            properties: {
                cloudflare_country: request.cf?.country,
                cloudflare_asn: request.cf?.asn,
                cloudflare_colo: request.cf?.colo,
                cloudflare_ray_id: request.headers.get('cf-ray'),
                cloudflare_bot_score: request.cf?.botManagement?.score,
                cloudflare_verified_bot: request.cf?.botManagement?.verifiedBot,
            },
        }),
    })
}
\`\`\``

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-cloudflare-worker',
    name: 'Cloudflare logs',
    description:
        'Capture HTTP request logs from a Cloudflare Worker as $http_log events. Powers bot analytics: crawlers and AI agents rarely execute JavaScript, so they only show up in server logs. Works on every Cloudflare plan.',
    icon_url: '/static/services/cloudflare.png',
    category: ['Infrastructure', 'Monitoring'],
    code_language: 'hog',
    code: HTTP_LOG_SOURCE_HOG_CODE,
    inputs_schema: httpLogSourceInputsSchema({
        authHeaderDescription: `Set this to "Bearer SECRET_TOKEN" with a random secret, and give the Worker the same secret. Without it, this endpoint accepts events for your project from anyone who knows the URL.

To set up the Worker:

1. In the Cloudflare dashboard, go to Workers & Pages, create a Worker, and paste the code below.
2. Add two variables in the Worker settings: \`POSTHOG_ENDPOINT\` (this source's webhook URL) and \`POSTHOG_SECRET\` (the secret, as an encrypted variable).
3. Add a route so the Worker runs on your traffic, e.g. \`example.com/*\`.

The Worker passes each request through to your origin unchanged and reports it in the background, so it does not delay responses. Only traffic proxied through Cloudflare (orange-cloud DNS) is visible to Workers.

${WORKER_SNIPPET}`,
    }),
}
