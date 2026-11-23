import type { StackProblem } from '@posthog/sdk/stack'

import { defineCommand } from '@/core/command'
import { EXIT_FAILURE, EXIT_SUCCESS } from '@/core/errors'
import { escapeControls, outputNotes, type Output } from '@/core/output'
import { checkStack, type CheckResult } from '@/stack/check'
import { resolveStack, stackOptions } from '@/stack/config'

function countText(counts: Record<string, number>): string {
    const parts = Object.entries(counts).map(
        ([kind, count]) => `${count} ${count === 1 ? kind : kind === 'entity' ? 'entities' : `${kind}s`}`
    )
    return parts.length > 0 ? parts.join(', ') : 'no definitions'
}

function problemLine(out: Output, problem: StackProblem): string {
    const where = problem.file ? `${problem.file}${problem.line ? `:${problem.line}` : ''}` : ''
    const subject = problem.kind && problem.key ? `${problem.kind} ${problem.key}` : ''
    const mark = problem.severity === 'error' ? out.style('error', 'red') : out.style('warning', 'yellow')
    return [
        mark,
        out.style(escapeControls(where), 'dim'),
        out.style(escapeControls(subject), 'bold'),
        escapeControls(problem.message),
    ]
        .filter(Boolean)
        .join('  ')
}

function typeCheckNote(typeCheck: CheckResult['typeCheck']): string | undefined {
    return typeCheck.compiler ? `Types checked with TypeScript ${escapeControls(typeCheck.compiler)}.` : undefined
}

export default defineCommand({
    description: 'Check a stack: type-check its definitions, evaluate them and validate every one',
    options: stackOptions,
    offline: true,
    scopes: [],
    notes: 'Runs on this machine and sends nothing to PostHog. Exits with code 1 when it finds a problem. `--raw` prints the result with the full description of the stack.',
    examples: ['hog check', 'hog stack check --stack slo-monitoring'],

    async run({ options, ctx }): Promise<CheckResult> {
        const stack = await resolveStack(ctx, options.stack, options.env)
        return checkStack(ctx, stack)
    },

    human({ result, out }) {
        const name = result.stack ?? result.dir
        const errors = result.problems.filter((problem) => problem.severity === 'error')
        const warnings = result.problems.filter((problem) => problem.severity === 'warning')
        const notes = [typeCheckNote(result.typeCheck)].filter((note): note is string => note !== undefined)
        notes.push(...outputNotes(result.output))
        if (result.ok) {
            out.report({
                result: `Stack ${name} passed check: ${countText(result.counts)}`,
                effects: warnings.map((problem) => problemLine(out, problem)),
                notes,
            })
            return
        }
        out.report({
            result: `Stack ${name} failed check: ${errors.length} ${errors.length === 1 ? 'problem' : 'problems'}`,
            status: 'failed',
            effects: result.problems.map((problem) => problemLine(out, problem)),
            notes,
        })
    },

    agent({ result, out }) {
        const { description: _description, ...summary } = result
        out.json(summary, { first: ['ok', 'problems'] })
    },

    exitCode: (result) => (result.ok ? EXIT_SUCCESS : EXIT_FAILURE),
})
