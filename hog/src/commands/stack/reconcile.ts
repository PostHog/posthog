import { defineCommand } from '@/core/command'
import { EXIT_NEEDS_PERSON, EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { resolveStack, stackOptions } from '@/stack/config'
import { pollDiff, pushCommand, reconcileCommand, selectorFlags, warningLines } from '@/stack/diff'
import { parseDiffId, stackService } from '@/stack/service'

export default defineCommand({
    description: 'After a push with an unknown outcome, accept the warnings of a new diff so the stack can push again',
    options: {
        ...stackOptions,
        diff: {
            type: 'string',
            placeholder: 'id',
            description: 'The ready diff, made since the uncertain push, whose warnings you accept',
            parse: parseDiffId,
        },
    },
    scopes: ['stack:write'],
    writes: true,
    notes: "This is a decision for a person at a terminal: hog shows the diff's warnings and asks. No option lets an agent or a script do it. Before you accept, adopt any listed entity the push already created with hog pull --adopt, or the push creates it a second time.",
    examples: ['hog stack reconcile --diff <id>'],

    async run({ ctx, options }) {
        const stack = await resolveStack(ctx, options.stack, options.env)
        if (!options.diff) {
            throw new HogError(
                'diff_required',
                'Reconciling needs the ID of a diff made since the uncertain push.',
                'Run hog diff, read its warnings, then pass its ID with --diff.',
                EXIT_USAGE
            )
        }
        const command = reconcileCommand(stack, options.diff)
        if (!ctx.prompts) {
            throw new HogError(
                'reconcile_needs_person',
                'Only a person can accept the warnings of an uncertain push.',
                `Show the person the warnings from hog diff --wait ${options.diff}${selectorFlags(stack)}, and ask them to run ${command} at a terminal.`,
                EXIT_NEEDS_PERSON
            )
        }
        const service = await stackService(ctx, stack)
        const saved = await pollDiff(ctx, service, options.diff)
        if (saved.status !== 'ready') {
            throw new HogError(
                'diff_not_ready',
                'This diff is not ready to reconcile with.',
                `Wait for it with hog diff --wait ${options.diff}${selectorFlags(stack)}, then run ${command} again.`
            )
        }
        const warnings = warningLines(saved.diff.warnings, stack, options.diff)
        ctx.prompts.note(
            escapeControls(
                (warnings.length
                    ? warnings
                    : ['This diff has no warnings about entities the push may have created.']
                ).join('\n')
            ),
            'Warnings'
        )
        if (
            !(await ctx.prompts.confirm('Accept these warnings and let this diff create its entities?', {
                initialValue: false,
            }))
        ) {
            return { status: 'cancelled' as const, id: options.diff }
        }
        const answer = await service.reconcile(options.diff)
        return {
            status: 'reconciled' as const,
            id: answer.diff_id,
            stack: answer.stack_name,
            acknowledged: answer.acknowledged_warnings,
            push: pushCommand(stack, answer.diff_id),
        }
    },
    human({ result, out }) {
        if (result.status === 'cancelled') {
            out.report({
                result: 'Nothing reconciled',
                status: 'unchanged',
                notes: [
                    'The stack still takes no push. Adopt the listed entities with hog pull --adopt, then run hog diff again.',
                ],
            })
            return
        }
        out.report({
            result: `Reconciled stack ${result.stack} with diff ${result.id}`,
            effects: [`Accepted ${result.acknowledged} ${result.acknowledged === 1 ? 'warning' : 'warnings'}`],
            notes: [`${result.push} can go ahead now.`],
        })
    },
    agent: ({ result, out }) => out.json(result),
})
