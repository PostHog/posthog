import { defineCommand } from '@/core/command'
import { escapeControls, Output } from '@/core/output'
import { plural } from '@/core/text'
import { findEndpoints, findInsightVariables } from '@/endpoints/api'
import { readEndpointFiles, type FileProblem } from '@/endpoints/files'
import { applyPush, planPush, pushScopes, type PushItem, type PushOutcome } from '@/endpoints/plan'

import {
    actionLabel,
    changeLines,
    CONFIRM_OPTIONS,
    confirm,
    endpointPaths,
    indent,
    problemWarnings,
    SCOPES_WRITE,
    variableLines,
    type Styler,
} from './shared'

type PlannedItem = Omit<PushItem, 'file'>

interface PushResult {
    status: 'applied' | 'preview' | 'cancelled' | 'nothing_to_do'
    plan: PlannedItem[]
    outcomes: PushOutcome[]
    problems: FileProblem[]
}

export function pushPlanLines(plan: PlannedItem[], style: Styler): string[] {
    return plan.flatMap((item) => [
        `${actionLabel(item.action, style)}  ${style(item.name, 'bold')}  ${style(item.path, 'dim')}`,
        ...indent(
            item.reason && item.action === 'skip' && item.reason !== 'No changes'
                ? [style(escapeControls(item.reason), 'yellow')]
                : []
        ),
        ...indent(item.changes.flatMap((change) => changeLines(change, 'push', style))),
        ...indent(variableLines(item.variables, style)),
    ])
}

export default defineCommand({
    description: 'Create or update PostHog endpoints from local YAML files',
    args: {
        paths: {
            description: 'Endpoint files, folders of them, or glob patterns. Defaults to endpoints.dir in posthog.json',
            variadic: true,
            optional: true,
        },
    },
    options: CONFIRM_OPTIONS,
    scopes: SCOPES_WRITE,
    notes: 'hog shows the changes and asks before it makes them. Agents and scripts pass --yes. hog creates the insight variables a file uses that the project lacks. Exits with code 1 when a file is invalid, PostHog would reject it, or an endpoint fails to save.',
    examples: [
        'hog endpoints push endpoints/',
        'hog endpoints push daily-signups.yaml --dry-run',
        'hog endpoints push --yes',
    ],

    async run({ args, options, ctx }): Promise<PushResult> {
        const { endpoints, problems } = await readEndpointFiles(ctx.runtime, await endpointPaths(ctx, args.paths))
        if (endpoints.length === 0) {
            return { status: 'nothing_to_do', plan: [], outcomes: [], problems }
        }
        const api = await ctx.posthog()
        const variableNames = endpoints.flatMap((local) => (local.file.variables ?? []).map(({ name }) => name))
        const [remotes, known] = await Promise.all([
            findEndpoints(
                api,
                endpoints.map((local) => local.file.name)
            ),
            findInsightVariables(api, variableNames),
        ])
        const variables = [...known.found.values()]
        const items = planPush(endpoints, [...remotes.values()], variables)
        const plan = items.map(({ file: _file, ...item }) => item)
        const pending = plan.filter((item) => item.action !== 'skip')
        if (pending.length === 0) {
            return { status: 'nothing_to_do', plan, outcomes: [], problems }
        }
        if (options.dryRun) {
            return { status: 'preview', plan, outcomes: [], problems }
        }
        const style = (text: string, ...styles: Parameters<Styler>[1][]): string =>
            new Output(ctx.runtime, ctx.mode).style(text, ...styles)
        const question = `Push ${plural(pending.length, 'endpoint')} to PostHog?`
        if (!(await confirm(ctx, options, pushPlanLines(pending, style), question))) {
            return { status: 'cancelled', plan, outcomes: [], problems }
        }
        await ctx.ensureScopes(pushScopes(items, variables))
        return { status: 'applied', plan, outcomes: await applyPush(api, items, variables, ctx.mode.isCI), problems }
    },

    human({ result, out }) {
        const style: Styler = (text, ...styles) => out.style(text, ...styles)
        const warnings = problemWarnings(result.problems)
        const invalid = result.problems.length > 0 || result.plan.some((item) => item.invalid)

        if (result.status === 'applied') {
            const failed = result.outcomes.filter((outcome) => outcome.status === 'failed').length
            const saved = result.outcomes.length - failed
            out.report({
                status: failed === 0 ? (invalid ? 'partial' : 'done') : saved === 0 ? 'failed' : 'partial',
                result:
                    failed === 0
                        ? `Pushed ${plural(saved, 'endpoint')}`
                        : `Pushed ${saved} of ${plural(result.outcomes.length, 'endpoint')}`,
                effects: result.outcomes.map((outcome) =>
                    outcome.status === 'failed'
                        ? `${out.style('Failed', 'red', 'bold')}   ${outcome.name}: ${escapeControls(outcome.error ?? '')}`
                        : `${out.style(outcome.status === 'created' ? 'Created' : 'Updated', 'green', 'bold')}  ${outcome.name}  ${out.style(escapeControls(outcome.uiUrl ?? ''), 'dim')}`
                ),
                warnings,
            })
            return
        }

        const messages = {
            preview: 'Dry run: nothing changed in PostHog',
            cancelled: 'Cancelled: nothing changed in PostHog',
            nothing_to_do: 'Nothing to push',
        }
        out.report({
            status: invalid ? 'partial' : 'unchanged',
            result: messages[result.status],
            effects: pushPlanLines(result.plan, style),
            warnings,
        })
    },

    agent({ result, out }) {
        out.json(result)
    },

    exitCode: (result) =>
        result.problems.length > 0 ||
        result.plan.some((item) => item.invalid) ||
        result.outcomes.some((outcome) => outcome.status === 'failed')
            ? 1
            : 0,

    telemetry: ({ result }) => ({
        status: result.status,
        file_count: result.plan.length,
        invalid_count: result.problems.length,
        created: result.outcomes.filter((outcome) => outcome.status === 'created').length,
        updated: result.outcomes.filter((outcome) => outcome.status === 'updated').length,
        failed: result.outcomes.filter((outcome) => outcome.status === 'failed').length,
    }),
})
