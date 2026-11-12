import { defineCommand } from '@/core/command'
import { findEndpoints } from '@/endpoints/api'
import { readEndpointFiles } from '@/endpoints/files'
import type { Endpoint } from '@/endpoints/model'
import { planPush } from '@/endpoints/plan'

import { pushPlanLines } from './push'
import { endpointPaths, problemWarnings, SCOPES_READ, type Styler } from './shared'

const inSync = (item: { action: string; reason?: string }): boolean =>
    item.action === 'skip' && item.reason === 'No changes'

export default defineCommand({
    description: 'Show how local endpoint files differ from PostHog',
    args: {
        paths: {
            description: 'Endpoint files, folders of them, or glob patterns. Defaults to endpoints.dir in posthog.json',
            variadic: true,
            optional: true,
        },
    },
    options: {
        verbose: { type: 'boolean', description: 'List the endpoints that match PostHog too' },
    },
    scopes: SCOPES_READ,
    notes: 'Exits with code 1 when a file differs from PostHog or is invalid, like `git diff --exit-code`, so CI can catch drift. `hog endpoints push` applies the changes.',
    examples: ['hog endpoints diff endpoints/', 'hog endpoints diff'],

    async run({ args, ctx }) {
        const { endpoints, problems } = await readEndpointFiles(ctx.runtime, await endpointPaths(ctx, args.paths))
        const names = endpoints.map((local) => local.file.name)
        const remotes = names.length > 0 ? await findEndpoints(await ctx.posthog(), names) : new Map<string, Endpoint>()
        // Variable types live on the project, so a diff only compares which variables each query uses.
        const plan = planPush(endpoints, [...remotes.values()], []).map(({ file: _file, ...item }) => item)
        return { plan, problems }
    },

    human({ result, out, options }) {
        const style: Styler = (text, ...styles) => out.style(text, ...styles)
        const shown = options.verbose ? result.plan : result.plan.filter((item) => !inSync(item))
        pushPlanLines(shown, style).forEach((line) => out.line(line))
        const count = (test: (item: (typeof result.plan)[number]) => boolean): number => result.plan.filter(test).length
        const parts = [
            `${count((item) => item.action === 'create')} new`,
            `${count((item) => item.action === 'update')} changed`,
            `${count(inSync)} unchanged`,
            `${count((item) => item.action === 'skip' && !inSync(item)) + result.problems.length} invalid`,
        ]
        out.line(out.style(parts.join(', '), 'dim'))
        out.notes({ warnings: problemWarnings(result.problems) })
    },

    agent({ result, out }) {
        out.json(result)
    },

    exitCode: (result) => (result.problems.length > 0 || !result.plan.every(inSync) ? 1 : 0),

    telemetry: ({ result }) => ({
        file_count: result.plan.length,
        changed: result.plan.filter((item) => !inSync(item)).length,
        invalid_count: result.problems.length,
    }),
})
