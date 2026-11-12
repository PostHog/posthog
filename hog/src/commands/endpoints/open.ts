import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { getEndpoint } from '@/endpoints/api'

import { SCOPES_READ } from './shared'

export default defineCommand({
    description: 'Open an endpoint in PostHog in your browser',
    args: { name: { description: 'The endpoint name' } },
    scopes: SCOPES_READ,
    notes: 'Agents get the link instead of a browser window.',
    examples: ['hog endpoints open daily-signups'],

    async run({ args, ctx }) {
        const endpoint = await getEndpoint(await ctx.posthog(), args.name)
        if (!endpoint.ui_url) {
            throw new HogError('no_ui_url', `PostHog didn't return a link for ${args.name}.`)
        }
        const opened = ctx.mode.agent === undefined && (await ctx.runtime.openUrl(endpoint.ui_url))
        return { name: endpoint.name, url: endpoint.ui_url, opened }
    },

    human({ result, out }) {
        if (result.opened) {
            out.report({
                result: `Opened ${escapeControls(result.name)} in the browser`,
                effects: [escapeControls(result.url)],
            })
            return
        }
        out.line(`Open ${escapeControls(result.url)}`)
    },
})
