import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'

import type { ResolvedStack } from './config'
import type { Evaluation } from './evaluation'

export interface CheckResult extends Evaluation {
    stack: string | undefined
    env: string | undefined
    dir: string
    ok: boolean
    counts: Record<string, number>
}

export async function checkStack(ctx: Context, stack: ResolvedStack): Promise<CheckResult> {
    if (!(await ctx.runtime.isDirectory(stack.path))) {
        throw new HogError(
            'stack_missing',
            `The stack folder ${stack.dir} doesn't exist.`,
            'Create it with an index.ts that exports your definitions, or set the folder under `stacks` in posthog.json.',
            EXIT_USAGE
        )
    }
    const evaluation = await ctx.runtime.evaluateStack(stack.path, stack.root).catch((error: unknown) => {
        if (error instanceof HogError) {
            throw error
        }
        throw new HogError(
            'stack_evaluation_failed',
            "hog couldn't run the stack check.",
            'Check that the folder is readable and its dependencies are installed, then run hog check again.'
        )
    })
    const counts: Record<string, number> = Object.create(null)
    for (const { kind } of evaluation.description.resources) {
        counts[kind] = (counts[kind] ?? 0) + 1
    }
    return {
        ...evaluation,
        stack: stack.name,
        env: stack.env,
        dir: stack.dir,
        ok:
            evaluation.typeCheck.status === 'passed' &&
            !evaluation.problems.some((problem) => problem.severity === 'error'),
        counts,
    }
}
