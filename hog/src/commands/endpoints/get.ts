import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { getEndpoint } from '@/endpoints/api'

import { materializationLabel, SCOPES_READ } from './shared'

export default defineCommand({
    description: 'Show an endpoint: its URLs, query, versions and materialization',
    args: { name: { description: 'The endpoint name' } },
    scopes: SCOPES_READ,
    examples: ['hog endpoints get daily-signups'],

    async run({ args, ctx }) {
        return getEndpoint(await ctx.posthog(), args.name)
    },

    human({ result: endpoint, out }) {
        const field = (label: string, value: string): void =>
            out.line(`  ${out.style(label.padEnd(12), 'bold')}${value}`)
        // Anyone in the project can edit this text, so escape sequences in it must not reach the terminal.
        const text = escapeControls
        if (endpoint.ui_url) {
            field('View', out.style(text(endpoint.ui_url), 'cyan'))
        }
        if (endpoint.url) {
            field('Run', out.style(text(endpoint.url), 'cyan'))
        }
        field('Name', text(endpoint.name))
        field('Status', endpoint.is_active ? out.style('active', 'green') : out.style('inactive', 'red'))
        if (endpoint.description) {
            field('Description', text(endpoint.description))
        }
        field('Version', `${endpoint.current_version ?? 1} (${endpoint.versions_count ?? 1} total)`)
        field('Refresh', materializationLabel(endpoint))
        const materialization = endpoint.materialization
        if (endpoint.is_materialized && materialization) {
            if (materialization.status) {
                field('Last run', text(materialization.status.toLowerCase()))
            }
            if (materialization.last_materialized_at) {
                field('Last done', text(materialization.last_materialized_at))
            }
            if (materialization.error) {
                field('Error', out.style(text(materialization.error), 'red'))
            }
        } else if (materialization && materialization.can_materialize === false && materialization.reason) {
            field('', out.style(text(materialization.reason), 'dim'))
        }
        field('Created', text(endpoint.created_at))
        field('Updated', text(endpoint.updated_at))
        out.line()
        out.line(`  ${out.style('Query', 'bold')}`)
        const query =
            typeof endpoint.query.query === 'string' ? endpoint.query.query : JSON.stringify(endpoint.query, null, 2)
        for (const line of query.split('\n')) {
            out.line(`    ${out.style(text(line), 'dim')}`)
        }
    },
})
