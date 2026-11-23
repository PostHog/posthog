import { z } from 'zod'

import type { StackDescription } from '@posthog/sdk/stack'

import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Spinner } from '@/core/prompts'
import type { Runtime } from '@/core/runtime'
import { stripCredentials } from '@/error-tracking/git'
import { isTransient } from '@/posthog/api'

import { checkStack } from './check'
import type { ResolvedStack } from './config'
import {
    stackService,
    type Diff,
    type DiffWarning,
    type SavedAnswer,
    type StackService,
    type StackSource,
} from './service'

const Commit = z.string().regex(/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i)
const Branch = z
    .string()
    .regex(/^[^\s\p{Cc}]+$/u)
    .max(500)

function repositoryName(remote: string): string {
    const clean = stripCredentials(remote)
    if (!clean) {
        return ''
    }
    const url = clean.includes('://') ? URL.parse(clean) : null
    const path =
        url && ['https:', 'http:', 'ssh:', 'git:'].includes(url.protocol)
            ? url.pathname.slice(1)
            : /^(?:[^@/:]+@)?[\w.-]+:([^?#]*)$/.exec(clean)?.[1]
    const name = path?.replace(/\/?$/, '').replace(/\.git$/, '')
    return name && /^[\w.-]+(?:\/[\w.-]+)+$/.test(name) ? name : ''
}

async function sourceFromGit(runtime: Runtime, root: string): Promise<StackSource> {
    const git = (args: string[]): ReturnType<Runtime['readCommand']> => runtime.readCommand(['git', ...args], root)
    const hint = 'Run hog diff in a git checkout with at least one commit.'
    try {
        const [origin, branch, head] = await Promise.all([
            git(['remote', 'get-url', 'origin']),
            git(['branch', '--show-current']),
            git(['rev-parse', 'HEAD']),
        ])
        const commit = Commit.safeParse(head.stdout.trim()).data
        if (head.exitCode !== 0 || !commit) {
            throw new Error()
        }
        const ref = branch.exitCode === 0 ? branch.stdout.trim() : ''
        return {
            repository: origin.exitCode === 0 ? repositoryName(origin.stdout.trim()) : '',
            branch: Branch.safeParse(ref || runtime.env.GITHUB_HEAD_REF || runtime.env.GITHUB_REF_NAME).data ?? '',
            commit,
        }
    } catch {
        throw new HogError('stack_source_missing', 'Could not read the git commit for these definitions.', hint)
    }
}

export async function startCheckedDiff(
    ctx: Context,
    stack: ResolvedStack
): Promise<{ id: string; service: StackService; description: StackDescription }> {
    const result = await checkStack(ctx, stack)
    if (!result.ok) {
        const problems = result.problems.filter((problem) => problem.severity === 'error')
        const lines = problems.map((problem) =>
            [problem.file, problem.kind, problem.key, problem.message].filter(Boolean).join(' ')
        )
        throw new HogError(
            'stack_check_failed',
            lines.join('\n'),
            'Fix the definitions reported by hog check, then run hog diff again.',
            undefined,
            { problems }
        )
    }
    const source = await sourceFromGit(ctx.runtime, stack.root)
    const service = await stackService(ctx, stack)
    const { id } = await service.create(result.description, source)
    return { id, service, description: result.description }
}

export type SavedDiff =
    | { status: 'running'; id: string; diff: null; operation?: 'push' | 'diff' }
    | { status: 'ready' | 'pushed'; id: string; diff: Diff; source?: StackSource; response: SavedAnswer }

export async function pollDiff(ctx: Context, service: StackService, id: string): Promise<SavedDiff> {
    let spinner: Spinner | undefined
    try {
        const result = await waitForDiff(ctx, service, id, () => {
            spinner ??= ctx.prompts?.spinner(`Waiting for PostHog (diff ${id})`)
        })
        spinner?.stop(result.status === 'running' ? 'PostHog is still working' : 'PostHog finished')
        return result
    } catch (error) {
        spinner?.error('PostHog could not finish')
        throw error
    }
}

async function waitForDiff(ctx: Context, service: StackService, id: string, waiting: () => void): Promise<SavedDiff> {
    const deadline = ctx.runtime.now() + 60_000
    let interval = 500
    let operation: 'push' | 'diff' | undefined
    while (ctx.runtime.now() < deadline) {
        const answer = await service.get(id, Math.min(10_000, deadline - ctx.runtime.now())).catch((error: unknown) => {
            if (error instanceof HogError && isTransient(error)) {
                return undefined
            }
            throw error
        })
        if (answer && (answer.status === 'ready' || answer.status === 'pushed')) {
            if (!answer.diff) {
                throw new HogError(
                    'unexpected_response',
                    'PostHog finished without returning the diff.',
                    'Run hog diff again.'
                )
            }
            return { id, status: answer.status, diff: answer.diff, source: answer.source, response: answer }
        }
        if (answer?.push_status !== undefined) {
            operation = answer.push_status === 'running' ? 'push' : 'diff'
        }
        waiting()
        await ctx.runtime.sleep(Math.max(0, Math.min(interval, deadline - ctx.runtime.now())))
        interval = Math.min(interval * 2, 3_000)
    }
    return { status: 'running', id, diff: null, operation }
}

export function selectorFlags(stack: ResolvedStack): string {
    return (stack.name ? ` --stack ${stack.name}` : '') + (stack.env ? ` --env ${stack.env}` : '')
}

export function pushCommand(stack: ResolvedStack, id: string): string {
    return `hog push --diff ${id}${selectorFlags(stack)}`
}

// Keys can be event names with spaces or quotes, so a suggested command quotes what the shell would split.
export function shellWord(value: string): string {
    return /^[\w.:/@+-]+$/.test(value) ? value : `'${value.replaceAll("'", "'\\''")}'`
}

export function reconcileCommand(stack: ResolvedStack, id: string): string {
    return `hog stack reconcile --diff ${id}${selectorFlags(stack)}`
}

// Shown above the changes: after a push with an unknown outcome, a create in this diff may make a second copy.
export function adoptCommand(stack: ResolvedStack, kind: string, key: string, entityId: string): string {
    return `hog stack adopt ${kind} ${shellWord(key)} ${shellWord(entityId)}${selectorFlags(stack)}`
}

// The warnings as an agent reads them: each with the command that binds each listed entity to its definition.
interface WarningWithCommands extends DiffWarning {
    adopt: string[]
}

export function warningsWithCommands(warnings: DiffWarning[], stack: ResolvedStack): WarningWithCommands[] {
    return warnings.map((warning) => ({
        ...warning,
        adopt:
            warning.key === null
                ? []
                : warning.entities.map((entity) => adoptCommand(stack, warning.kind, warning.key!, entity.entity_id)),
    }))
}

export function warningLines(warnings: DiffWarning[], stack: ResolvedStack, id: string): string[] {
    if (!warnings.length) {
        return []
    }
    const lines = ['Warning: an earlier push stopped without a known outcome, and it may already have created these:']
    for (const warning of warnings) {
        lines.push(`  ${warning.kind}${warning.key ? ` ${warning.key}` : ''}  ${warning.message}`)
        for (const entity of warning.entities) {
            lines.push(`      ID ${entity.entity_id}  ${entity.name}`)
        }
    }
    const candidate = warnings.find((warning) => warning.entities.length && warning.key !== null)
    const adopt = candidate
        ? adoptCommand(stack, candidate.kind, candidate.key!, candidate.entities[0]!.entity_id)
        : `hog stack adopt <kind> <key> <ID>${selectorFlags(stack)}`
    lines.push(
        '',
        'Choose one before pushing:',
        `  If an entity listed here is the one the definition means, bind it to the definition, as in ${adopt}, then run hog diff again.`,
        `  If the creates should go ahead, a person accepts these warnings with ${reconcileCommand(stack, id)}.`,
        ''
    )
    return lines
}

export function diffBlock(
    diff: Diff,
    service: Pick<StackService, 'name' | 'project'>,
    pullRequest: boolean,
    pushed = false,
    warnings: string[] = []
): string {
    const heading = pullRequest ? 'PostHog changes in this pull request' : 'PostHog changes'
    const lines = [`${heading} (stack ${service.name}, project ${service.project})`, '', ...warnings]
    const signs = { create: '+', update: '~', recreate: '!', remove: '-', adopt: '+', rename: '~', release: '-' }
    for (const change of diff.changes) {
        lines.push(
            `  ${signs[change.action]} ${change.action}  ${change.kind}  ${change.key}  ${change.summary}  ${change.source?.file ?? '(source file unavailable)'}`
        )
        if (change.action === 'recreate' && change.loses) {
            lines.push(`      Loses: ${change.loses}`)
        }
        if (change.action === 'adopt' && change.entity_id) {
            lines.push(`      Existing entity ID: ${change.entity_id}`)
        }
        for (const field of change.fields.filter((field) => field.hidden)) {
            lines.push(`      ${field.path}  (hidden)`)
        }
    }
    if (!diff.changes.length) {
        lines.push('  No changes')
    }
    lines.push(`  ${diff.summary.remove} removed`)
    if (diff.drift.length) {
        lines.push('', 'Drift')
        for (const item of diff.drift) {
            if (item.deleted) {
                lines.push(`  ${item.kind} ${item.key} was removed in PostHog`)
            }
            for (const field of item.fields) {
                // A pull request can be read by people the service would not show these values to.
                const change = pullRequest
                    ? ''
                    : field.hidden
                      ? '  (hidden)'
                      : `  ${JSON.stringify(field.pushed)} → ${JSON.stringify(field.found)}`
                lines.push(`  ${item.kind} ${item.key}  ${field.path}${change}`)
            }
        }
    }
    const notes = [...(diff.notes ?? [])]
    if (pullRequest && diff.drift.some((item) => item.fields.length)) {
        notes.push('Drift values are left out of the pull request. People allowed to see them can run hog diff.')
    }
    if (diff.changes.length && !pushed) {
        notes.push(pullRequest ? 'Nothing here is live yet. Push it after the merge.' : 'Nothing here is live yet.')
    }
    if (notes.length) {
        lines.push('', ...notes)
    }
    return escapeControls(lines.join('\n'))
}
