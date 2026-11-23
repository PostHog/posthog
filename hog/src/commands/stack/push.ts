import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { EXIT_NEEDS_PERSON, EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { resolveStack, stackOptions } from '@/stack/config'
import { diffBlock, pollDiff, selectorFlags, startCheckedDiff, warningLines } from '@/stack/diff'
import { actions, parseDiffId, stackService, waitOption } from '@/stack/service'

const MaxRemovals = z
    .string()
    .regex(/^\d+$/, 'Use a whole number of zero or more.')
    .transform(Number)
    .pipe(z.int().nonnegative())
const past = {
    create: 'created',
    update: 'updated',
    recreate: 'recreated',
    remove: 'removed',
    adopt: 'adopted',
    release: 'released',
    rename: 'renamed',
}

export default defineCommand({
    description: 'Push the exact changes in a saved diff',
    options: {
        ...stackOptions,
        diff: { type: 'string', placeholder: 'id', description: 'Push the diff with this ID', parse: parseDiffId },
        wait: waitOption,
        maxRemovals: {
            type: 'string',
            placeholder: 'count',
            description:
                'Allow this many removals and recreations for this push. Only a person at a terminal can pass it: hog shows what the push removes and recreates and asks. No option lets an agent or a script raise the limit',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(MaxRemovals, raw, failure),
        },
    },
    scopes: ['stack:write'],
    writes: true,
    examples: ['hog push --diff <id>', 'hog push --wait <id>', 'hog push'],
    async run({ ctx, options }) {
        if (options.wait && (options.diff || options.maxRemovals !== undefined)) {
            throw new HogError(
                'usage_error',
                '--wait only reads the result of an existing push.',
                'Pass --wait on its own, or pass --diff to start a push.',
                EXIT_USAGE
            )
        }
        if (options.maxRemovals !== undefined && !ctx.prompts) {
            const push = `hog push${options.diff ? ` --diff ${options.diff}` : ''}${options.stack ? ` --stack ${options.stack}` : ''}${options.env ? ` --env ${options.env}` : ''} --max-removals ${options.maxRemovals}`
            throw new HogError(
                'max_removals_needs_person',
                'Only a person can raise the limit on removals and recreations.',
                `Ask a person to run ${push} at a terminal, where hog shows what the push removes and recreates and asks them to confirm.`,
                EXIT_NEEDS_PERSON
            )
        }
        if (!options.wait && !options.diff && !ctx.prompts) {
            throw new HogError(
                'diff_required',
                'This push needs a saved diff ID.',
                'Run hog diff, review the changes, then run hog push --diff <id>.',
                EXIT_USAGE
            )
        }
        const stack = await resolveStack(ctx, options.stack, options.env)
        const specified = options.wait ?? options.diff
        const { id, service } = specified
            ? { id: specified, service: await stackService(ctx, stack) }
            : await startCheckedDiff(ctx, stack)
        if (!specified || options.maxRemovals !== undefined) {
            const saved = await pollDiff(ctx, service, id)
            if (saved.status === 'running') {
                return {
                    status: 'running',
                    id,
                    next: `hog diff --wait ${id}${selectorFlags(stack)}`,
                    operation: 'diff',
                } as const
            }
            if (!specified) {
                ctx.prompts!.note(
                    diffBlock(saved.diff, service, false, false, warningLines(saved.diff.warnings, stack, id)),
                    'Changes'
                )
                if (!(await ctx.prompts!.confirm('Push these changes?', { initialValue: false }))) {
                    return { status: 'cancelled', id } as const
                }
            }
            if (options.maxRemovals !== undefined) {
                const losing = saved.diff.changes.filter(
                    (change) => change.action === 'remove' || change.action === 'recreate'
                )
                const lines = losing.map((change) =>
                    escapeControls(
                        `${change.action}  ${change.kind}  ${change.key}${change.loses ? `  Loses: ${change.loses}` : ''}`
                    )
                )
                ctx.prompts!.note(
                    lines.length ? lines.join('\n') : 'This diff removes and recreates nothing.',
                    'Removed or recreated'
                )
                if (
                    !(await ctx.prompts!.confirm(
                        `Allow up to ${options.maxRemovals} removals and recreations in this push?`,
                        { initialValue: false }
                    ))
                ) {
                    return { status: 'cancelled', id } as const
                }
            }
        }
        if (!options.wait) {
            await service.push(id, options.maxRemovals)
        }
        const saved = await pollDiff(ctx, service, id)
        if (saved.status === 'running') {
            if (saved.operation === 'diff') {
                return {
                    status: 'running',
                    id,
                    next: `hog diff --wait ${id}${selectorFlags(stack)}`,
                    operation: 'diff',
                } as const
            }
            return {
                status: 'running',
                id,
                next: `hog push --wait ${id}${selectorFlags(stack)}`,
                operation: 'push',
            } as const
        }
        if (saved.status !== 'pushed') {
            throw new HogError(
                'push_not_started',
                'This diff is ready and has no completed push.',
                `Review it with hog diff --wait ${id}${selectorFlags(stack)}, then pass --diff to push it.`
            )
        }
        return {
            status: 'pushed',
            id,
            changes: saved.diff.changes,
            summary: saved.diff.summary,
            response: saved.response,
        } as const
    },
    human({ result, out }) {
        if (result.status === 'running') {
            out.report({ result: `The ${result.operation} is running`, notes: [`Run ${result.next} to wait for it.`] })
        } else if (result.status === 'cancelled') {
            out.report({ result: 'Push cancelled', status: 'unchanged' })
        } else {
            const counts = actions.map((action) => `${result.summary[action] ?? 0} ${past[action]}`)
            out.report({
                result: `Pushed diff ${result.id}`,
                effects: [
                    counts.join(', '),
                    ...result.changes.map((change) =>
                        escapeControls(`${past[change.action]}  ${change.kind}  ${change.key}`)
                    ),
                ],
                notes: result.response.diff?.notes,
            })
        }
    },
    agent({ result, out }) {
        const data =
            result.status === 'pushed'
                ? {
                      status: result.status,
                      id: result.id,
                      changes: result.changes,
                      summary: result.summary,
                      notes: result.response.diff?.notes,
                  }
                : result
        out.json(data, { first: ['status', 'id', 'next'] })
    },
    raw: (result) => (result.status === 'pushed' ? result.response : result),
    exitCode: (result) => (result.status === 'running' ? EXIT_PENDING : EXIT_SUCCESS),
})
