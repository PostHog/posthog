import { diffLines } from 'diff'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Style } from '@/core/output'
import { absolutePath } from '@/core/paths'
import type { Change } from '@/endpoints/changes'
import type { FileProblem } from '@/endpoints/files'
import { SCHEDULE_LABELS, scheduleFor, type Endpoint } from '@/endpoints/model'
import type { VariableChange } from '@/endpoints/plan'

export type Styler = (text: string, ...styles: Style[]) => string

export const SCOPES_READ = ['endpoint:read'] as const
export const SCOPES_WRITE = [
    'endpoint:read',
    'endpoint:write',
    'insight_variable:read',
    'insight_variable:write',
] as const

export const CONFIRM_OPTIONS = {
    dryRun: { type: 'boolean', description: 'Show the changes without making them' },
    yes: { type: 'boolean', short: 'y', description: 'Make the changes without asking. Agents and scripts need it' },
} as const

export function summary(endpoint: Endpoint): Record<string, unknown> {
    return {
        name: endpoint.name,
        description: endpoint.description ?? '',
        active: endpoint.is_active,
        materialized: endpoint.is_materialized,
        schedule: endpoint.is_materialized ? (scheduleFor(endpoint.data_freshness_seconds) ?? null) : null,
        url: endpoint.url ?? null,
        uiUrl: endpoint.ui_url ?? null,
    }
}

export function materializationLabel(endpoint: Endpoint): string {
    if (!endpoint.is_materialized) {
        return 'on demand'
    }
    const schedule = scheduleFor(endpoint.data_freshness_seconds)
    return `materialized, ${schedule ? SCHEDULE_LABELS[schedule] : 'scheduled'}`
}

// The paths a push or diff reads: the arguments, or `endpoints.dir` from posthog.json.
export async function endpointPaths(ctx: Context, paths: readonly string[]): Promise<string[]> {
    if (paths.length > 0) {
        return [...paths]
    }
    const loaded = await ctx.config()
    const dir = loaded?.config.endpoints?.dir
    if (loaded && dir) {
        return [absolutePath(loaded.root, dir)]
    }
    throw new HogError(
        'paths_required',
        'Pass the endpoint files or folders to read.',
        'Or set endpoints.dir in posthog.json to the folder that holds them.',
        EXIT_USAGE
    )
}

// Asks a person before changes happen. Agents and scripts can't answer, so they pass --yes.
export async function confirm(
    ctx: Context,
    options: { yes?: boolean },
    preview: string[],
    question: string
): Promise<boolean> {
    if (options.yes) {
        return true
    }
    if (!ctx.prompts) {
        throw new HogError(
            'confirmation_required',
            'hog needs a confirmation before it makes these changes.',
            'Pass --yes to make them, or --dry-run to only see them.'
        )
    }
    ctx.prompts.note(preview.join('\n'), 'Changes')
    return ctx.prompts.confirm(question)
}

const LABELS: Record<Change['field'], string> = {
    description: 'Description',
    query: 'Query',
    materialization: 'Materialization',
    schedule: 'Schedule',
    variables: 'Variables',
    defaults: 'Defaults',
}

// `from` is the side that changes: PostHog for a push, the file for a pull. Anyone in the project
// can edit the PostHog side, so escape sequences in it must not reach the terminal.
export function changeLines(change: Change, direction: 'push' | 'pull', style: Styler): string[] {
    const [from, to] = direction === 'push' ? [change.remote, change.local] : [change.local, change.remote]
    if (change.field !== 'query') {
        return [`${LABELS[change.field]}: ${escapeControls(from) || '(none)'} → ${escapeControls(to) || '(none)'}`]
    }
    const lines = [`${LABELS.query}:`]
    for (const part of diffLines(from.endsWith('\n') ? from : `${from}\n`, to.endsWith('\n') ? to : `${to}\n`)) {
        const sign = part.added ? '+' : part.removed ? '-' : ' '
        const color: Style = part.added ? 'green' : part.removed ? 'red' : 'dim'
        for (const line of part.value.replace(/\n$/, '').split('\n')) {
            lines.push(style(`  ${sign} ${escapeControls(line)}`, color))
        }
    }
    return lines
}

export function variableLines(changes: VariableChange[], style: Styler): string[] {
    if (changes.length === 0) {
        return []
    }
    return [
        'Variables:',
        ...changes.map((change) => {
            // A name can come from the endpoint in PostHog, which another member can edit.
            const name = escapeControls(change.name)
            if (change.change === 'add') {
                return style(`  + ${name} (${escapeControls(change.type ?? '')})`, 'green')
            }
            if (change.change === 'retype') {
                return style(
                    `  ~ ${name} (${escapeControls(change.from ?? '')} → ${escapeControls(change.type ?? '')})`,
                    'yellow'
                )
            }
            return style(`  - ${name}`, 'red')
        }),
    ]
}

export function actionLabel(action: 'create' | 'update' | 'skip', style: Styler): string {
    const labels = {
        create: style('create', 'green', 'bold'),
        update: style('update', 'yellow', 'bold'),
        skip: style('skip  ', 'dim'),
    }
    return labels[action]
}

export function problemLines(problems: FileProblem[], style: Styler): string[] {
    return problems.map((problem) => `${style('Skipped', 'yellow', 'bold')} ${problem.path}: ${problem.message}`)
}

export function indent(lines: string[], by = '    '): string[] {
    return lines.map((line) => `${by}${line}`)
}
