import { defineCommand } from '@/core/command'
import { plural } from '@/core/text'
import { listEndpoints } from '@/endpoints/api'

import { materializationLabel, SCOPES_READ, summary } from './shared'

export default defineCommand({
    description: 'List the endpoints in your project',
    scopes: SCOPES_READ,
    examples: ['hog endpoints list'],

    async run({ ctx }) {
        const api = await ctx.posthog()
        return { projectId: (await ctx.credentials()).projectId, endpoints: await listEndpoints(api) }
    },

    human({ result, out }) {
        if (result.endpoints.length === 0) {
            out.line(`No endpoints in project ${result.projectId} yet.`)
            out.line(`Create one from a YAML file with ${out.style('hog endpoints push my-endpoint.yaml', 'bold')}.`)
            return
        }
        out.table(
            ['name', 'refresh', 'active', 'description'],
            result.endpoints.map((endpoint) => [
                endpoint.name,
                materializationLabel(endpoint),
                endpoint.is_active,
                endpoint.description ?? '',
            ])
        )
        out.line(out.style(`${plural(result.endpoints.length, 'endpoint')} in project ${result.projectId}`, 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result.endpoints.map(summary))
    },

    telemetry: ({ result }) => ({ endpoint_count: result.endpoints.length }),
})
