import { defineNativeTool, Type } from '@posthog/agent-shared'

import { parseFetchableUrl } from './http-url'

export const webFetchV1 = defineNativeTool({
    id: '@posthog/web-fetch',
    description:
        'GET a URL and return its body. Outbound host filtering is enforced at the infrastructure layer (smokescreen egress proxy).',
    args: Type.Object({
        url: Type.String({ format: 'uri' }),
        max_bytes: Type.Optional(Type.Integer({ minimum: 1, maximum: 5_000_000, default: 1_000_000 })),
    }),
    returns: Type.Object({
        status: Type.Number(),
        body: Type.String(),
        content_type: Type.String(),
        url: Type.String(),
    }),
    requires: { integrations: [], scopes: ['web:fetch'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const maxBytes = args.max_bytes ?? 1_000_000
        // Pin the scheme to http/https before fetching (SSRF host filtering is
        // smokescreen's job at the egress hop).
        parseFetchableUrl(args.url)
        const res = await ctx.http.fetch(args.url, { method: 'GET' })
        const text = await res.text()
        return {
            status: res.status,
            body: text.length > maxBytes ? text.slice(0, maxBytes) : text,
            content_type: res.headers.get('content-type') ?? '',
            url: args.url,
        }
    },
})
