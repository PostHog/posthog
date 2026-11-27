import { defineCommand } from '@/core/command'
import { listEndpoints } from '@/endpoints/api'
import { MAX_LIMIT, nextOffset, parseLimit, parseOffset } from '@/posthog/pagination'

import { materializationLabel, SCOPES_READ, summary } from './shared'

const DEFAULT_LIMIT = 100

export default defineCommand({
    description: 'List the endpoints in your project, one page at a time',
    options: {
        limit: {
            type: 'string',
            placeholder: 'count',
            parse: parseLimit,
            description: `How many endpoints to show, up to ${MAX_LIMIT}. Defaults to ${DEFAULT_LIMIT}`,
        },
        offset: {
            type: 'string',
            placeholder: 'count',
            parse: parseOffset,
            description: 'How many endpoints to skip. Each page ends with the offset of the next one',
        },
    },
    scopes: SCOPES_READ,
    examples: ['hog endpoints list', 'hog endpoints list --limit 20 --offset 40'],

    async run({ options, ctx }) {
        const offset = options.offset ?? 0
        const page = await listEndpoints(await ctx.posthog(), options.limit ?? DEFAULT_LIMIT, offset)
        return {
            projectId: (await ctx.credentials()).key.projectId,
            endpoints: page.results,
            count: page.count ?? null,
            offset,
            nextOffset: nextOffset(page),
        }
    },

    human({ result, options, out }) {
        if (result.endpoints.length === 0) {
            if (result.offset > 0) {
                out.line(`No endpoints after the first ${result.offset} in project ${result.projectId}.`)
                return
            }
            out.line(`No endpoints in project ${result.projectId} yet.`)
            out.notes({
                notes: [
                    `Create one from a YAML file with ${out.style('hog endpoints push my-endpoint.yaml', 'bold')}.`,
                ],
            })
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
        const shown = `${result.offset + 1}-${result.offset + result.endpoints.length}`
        const total = result.count === null ? '' : ` of ${result.count}`
        out.line(out.style(`Endpoints ${shown}${total} in project ${result.projectId}`, 'dim'))
        if (result.nextOffset !== null) {
            const limit = options.limit === undefined ? '' : ` --limit ${options.limit}`
            const command = `hog endpoints list --offset ${result.nextOffset}${limit}`
            out.notes({ notes: [`Run ${out.style(command, 'bold')} for the next page.`] })
        }
    },

    agent({ result, out }) {
        out.json({ endpoints: result.endpoints.map(summary), count: result.count, nextOffset: result.nextOffset })
    },

    telemetry: ({ result }) => ({ endpoint_count: result.endpoints.length, has_next: result.nextOffset !== null }),
})
