import { defineCommand } from '@/core/command'
import { EXIT_CHANGES, EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import { DRY_RUN_ENV, envFlag } from '@/core/globals'
import { commentOnPullRequest } from '@/stack/comment'
import { resolveStack, stackOptions } from '@/stack/config'
import {
    diffBlock,
    pollDiff,
    pushCommand,
    reconcileCommand,
    selectorFlags,
    startCheckedDiff,
    warningLines,
    warningsWithCommands,
} from '@/stack/diff'
import { stackService, waitOption } from '@/stack/service'

export default defineCommand({
    description: 'Show what pushing the stack would change in PostHog',
    options: {
        ...stackOptions,
        wait: waitOption,
        comment: {
            type: 'boolean',
            description: 'Post the changes on the current GitHub pull request or update the earlier comment',
        },
    },
    scopes: ['stack:read'],
    examples: ['hog diff', 'hog diff --comment', 'hog diff --wait <id>'],
    notes: 'Runs hog check before sending the definitions. Exits with 5 for changes or drift and 4 while the diff is running.',
    async run({ ctx, options }) {
        if (options.comment && envFlag(ctx.runtime.env, DRY_RUN_ENV)) {
            throw new HogError(
                'dry_run_unsupported',
                '--comment would write to the pull request while HOG_DRY_RUN is set.',
                'Omit --comment to read the diff or unset HOG_DRY_RUN to post it.',
                EXIT_USAGE
            )
        }
        const stack = await resolveStack(ctx, options.stack, options.env)
        const { service, id } = options.wait
            ? { service: await stackService(ctx, stack), id: options.wait }
            : await startCheckedDiff(ctx, stack)
        const saved = await pollDiff(ctx, service, id)
        if (saved.status === 'running') {
            if (saved.operation === 'push') {
                const next = options.comment
                    ? `hog diff --wait ${id}${selectorFlags(stack)} --comment`
                    : `hog push --wait ${id}${selectorFlags(stack)}`
                return { status: saved.status, id, operation: 'push', next } as const
            }
            return {
                status: saved.status,
                id,
                next: `hog diff --wait ${id}${selectorFlags(stack)}${options.comment ? ' --comment' : ''}`,
            } as const
        }
        const push = saved.status === 'ready' ? pushCommand(stack, id) : undefined
        const warnings = saved.status === 'ready' ? warningLines(saved.diff.warnings, stack, id) : []
        const report = diffBlock(saved.diff, service, options.comment === true, saved.status === 'pushed', warnings)
        const pushLine = warnings.length
            ? `Once a person reconciled the stack, push this diff with ${push}.`
            : `Push this diff with ${push}.`
        const block = push && !options.comment ? `${report}\n\n${pushLine}` : report
        if (options.comment) {
            try {
                await commentOnPullRequest(ctx.runtime, stack, String(service.project), block)
            } catch (error) {
                if (!(error instanceof HogError)) {
                    throw error
                }
                const next = `hog diff --wait ${id}${selectorFlags(stack)} --comment`
                throw new HogError(
                    error.code,
                    error.message,
                    `${error.hint ?? 'Check the pull request.'} Retry the saved diff with ${next}.`,
                    error.exitCode,
                    { id, next }
                )
            }
        }
        const next = warnings.length
            ? { warnings: warningsWithCommands(saved.diff.warnings, stack), reconcile: reconcileCommand(stack, id) }
            : {}
        return {
            status: saved.status,
            id,
            push,
            block,
            diff: saved.diff,
            next,
            source: saved.source,
            response: saved.response,
        } as const
    },
    human({ result, out }) {
        if (result.status === 'running') {
            out.line(
                `${'operation' in result && result.operation === 'push' ? 'Push for diff' : 'Diff'} ${result.id} is running.`
            )
            out.notes({ notes: [`Run ${result.next} to wait for the changes.`] })
            return
        }
        out.line(result.block)
    },
    agent({ result, out }) {
        if (result.status === 'running') {
            out.json(result)
        } else {
            out.json(
                {
                    status: result.status,
                    id: result.id,
                    push: result.push,
                    source: result.source,
                    ...result.diff,
                    ...result.next,
                },
                { first: ['status', 'id', 'warnings', 'push'] }
            )
        }
    },
    raw: (result) => (result.status === 'running' ? result : result.response),
    exitCode: (result) =>
        result.status === 'running'
            ? EXIT_PENDING
            : result.diff.changes.length || result.diff.drift.length
              ? EXIT_CHANGES
              : EXIT_SUCCESS,
})
