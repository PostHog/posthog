import { basename, join, relative } from 'node:path'
import { stringify } from 'yaml'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { Output } from '@/core/output'
import { absolutePath } from '@/core/paths'
import { plural } from '@/core/text'
import { listEndpoints, listInsightVariables } from '@/endpoints/api'
import { readEndpointFiles, type FileProblem } from '@/endpoints/files'
import { fileFromEndpoint, remoteVariableNames } from '@/endpoints/model'
import { planPull, type PullItem } from '@/endpoints/plan'
import { ApiError, type PostHogApi } from '@/posthog/api'

import { actionLabel, changeLines, CONFIRM_OPTIONS, confirm, indent, SCOPES_READ, type Styler } from './shared'

type PlannedItem = Omit<PullItem, 'endpoint'>

interface PullResult {
    status: 'written' | 'preview' | 'cancelled' | 'nothing_to_do'
    plan: PlannedItem[]
    written: string[]
    problems: FileProblem[]
}

const isYamlFile = (path: string): boolean => /\.ya?ml$/i.test(path)

function pullPlanLines(plan: PlannedItem[], style: Styler): string[] {
    return plan
        .filter((item) => item.action !== 'skip')
        .flatMap((item) => [
            `${actionLabel(item.action, style)}  ${style(item.path, 'bold')}`,
            ...indent(item.changes.flatMap((change) => changeLines(change, 'pull', style))),
        ])
}

// posthog-cli pulls with only endpoint:read. A key that can't read the project's variables gets
// each type from the variable's value instead, as posthog-cli does.
async function variableTypes(api: PostHogApi): Promise<Map<string, string>> {
    try {
        return new Map((await listInsightVariables(api)).map((variable) => [variable.code_name, variable.type]))
    } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
            return new Map()
        }
        throw error
    }
}

export function endpointYaml(path: string, item: PullItem, types: ReadonlyMap<string, string>): string {
    const body = stringify(fileFromEndpoint(item.endpoint, types), { lineWidth: 0, blockQuote: 'literal' })
    return `# ${basename(path)}\n${body}`
}

export default defineCommand({
    description: 'Write PostHog endpoints to local YAML files',
    args: { names: { description: 'The endpoints to pull', variadic: true, optional: true } },
    options: {
        all: { type: 'boolean', description: 'Pull every endpoint in the project' },
        to: {
            type: 'string',
            placeholder: 'path',
            description:
                'A folder, or a .yaml file when pulling one endpoint. Defaults to endpoints.dir in posthog.json, then .',
        },
        ...CONFIRM_OPTIONS,
    },
    scopes: SCOPES_READ,
    notes: 'An endpoint a local file already defines updates that file. Others go to <folder>/<name>.yaml. hog shows the changes and asks before it writes; agents and scripts pass --yes. Exits with code 1 when an endpoint is missing or a file is left alone.',
    examples: [
        'hog endpoints pull daily-signups',
        'hog endpoints pull --all --to endpoints/',
        'hog endpoints pull --all --yes',
    ],

    async run({ args, options, ctx }): Promise<PullResult> {
        if (!options.all && args.names.length === 0) {
            throw new HogError(
                'usage_error',
                'Pass the endpoints to pull, or --all.',
                'Run `hog endpoints list` to see the names.',
                EXIT_USAGE
            )
        }
        const loaded = await ctx.config()
        const configured = loaded?.config.endpoints?.dir
        const target =
            options.to !== undefined
                ? absolutePath(ctx.runtime.cwd(), options.to)
                : loaded && configured
                  ? absolutePath(loaded.root, configured)
                  : ctx.runtime.cwd()
        const fileTarget = isYamlFile(target)

        const remotes = await listEndpoints(await ctx.posthog())
        const problems: FileProblem[] = []
        let selected = remotes
        if (!options.all) {
            const known = new Set(remotes.map((endpoint) => endpoint.name))
            const missing = args.names.filter((name) => !known.has(name))
            if (missing.length === args.names.length) {
                throw new HogError(
                    'endpoint_not_found',
                    `PostHog has no endpoint named ${missing.join(', ')}.`,
                    'Run `hog endpoints list` to see the names.'
                )
            }
            problems.push(...missing.map((name) => ({ path: name, message: 'PostHog has no endpoint with this name' })))
            selected = remotes.filter((endpoint) => args.names.includes(endpoint.name))
        }
        if (fileTarget && selected.length > 1) {
            throw new HogError(
                'usage_error',
                `--to names one file, but there are ${plural(selected.length, 'endpoint')} to pull.`,
                'Pass a folder, or pull one endpoint at a time.',
                EXIT_USAGE
            )
        }

        const scan = fileTarget
            ? (await ctx.runtime.exists(target))
                ? [target]
                : []
            : (await ctx.runtime.isDirectory(target))
              ? [target]
              : []
        const { endpoints: locals, problems: unreadable } = await readEndpointFiles(ctx.runtime, scan)
        const cwd = ctx.runtime.cwd()
        const claimed = new Set(locals.map((local) => absolutePath(cwd, local.path)))
        const broken = new Map(unreadable.map((problem) => [absolutePath(cwd, problem.path), problem.message]))
        const written = new Set<string>()
        // Never write a file twice, replace a file that defines another endpoint, or overwrite one hog can't read.
        const items = planPull(selected, locals, (name) => (fileTarget ? target : join(target, `${name}.yaml`))).map(
            (planned): PullItem => {
                const item = { ...planned, path: absolutePath(cwd, planned.path) }
                const blocked = written.has(item.path)
                    ? 'Another endpoint pulled to the same file'
                    : item.action === 'create' && broken.has(item.path)
                      ? `The file exists but hog can't read it (${broken.get(item.path)}), so hog leaves it alone`
                      : item.action === 'create' && claimed.has(item.path)
                        ? 'The file defines another endpoint'
                        : undefined
                if (blocked) {
                    problems.push({ path: relative(cwd, item.path) || item.path, message: `${item.name}: ${blocked}` })
                    return { ...item, action: 'skip', reason: blocked }
                }
                if (item.action !== 'skip') {
                    written.add(item.path)
                }
                return item
            }
        )
        const shown = (path: string): string => relative(ctx.runtime.cwd(), path) || path
        const plan = items.map(({ endpoint: _endpoint, ...item }) => ({ ...item, path: shown(item.path) }))
        const pending = items.filter((item) => item.action !== 'skip')
        if (pending.length === 0) {
            return { status: 'nothing_to_do', plan, written: [], problems }
        }
        if (options.dryRun) {
            return { status: 'preview', plan, written: [], problems }
        }
        const style: Styler = (text, ...styles) => new Output(ctx.runtime, ctx.mode).style(text, ...styles)
        if (!(await confirm(ctx, options, pullPlanLines(plan, style), `Write ${plural(pending.length, 'file')}?`))) {
            return { status: 'cancelled', plan, written: [], problems }
        }
        const types = pending.some((item) => remoteVariableNames(item.endpoint).length > 0)
            ? await variableTypes(await ctx.posthog())
            : new Map<string, string>()
        for (const item of pending) {
            await ctx.runtime.writeFile(item.path, endpointYaml(item.path, item, types))
        }
        return { status: 'written', plan, written: pending.map((item) => shown(item.path)), problems }
    },

    human({ result, out }) {
        const style: Styler = (text, ...styles) => out.style(text, ...styles)
        for (const problem of result.problems) {
            out.line(`${out.style('Skipped', 'yellow', 'bold')} ${problem.path}: ${problem.message}`)
        }
        if (result.status === 'written') {
            result.written.forEach((path) => out.line(`${out.style('Wrote', 'green', 'bold')}  ${path}`))
            out.line(out.style(`${plural(result.written.length, 'file')} written`, 'dim'))
            return
        }
        pullPlanLines(result.plan, style).forEach((line) => out.line(line))
        const messages = {
            preview: 'Dry run: no files written.',
            cancelled: 'Cancelled: no files written.',
            nothing_to_do: 'The local files already match PostHog.',
        }
        out.line(out.style(messages[result.status], 'dim'))
    },

    agent({ result, out }) {
        out.json(result)
    },

    exitCode: (result) => (result.problems.length > 0 ? 1 : 0),

    telemetry: ({ result, options }) => ({
        status: result.status,
        all: options.all === true,
        endpoint_count: result.plan.length,
        written: result.written.length,
    }),
})
