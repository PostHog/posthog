import { join } from 'node:path'
import type { z } from 'zod'

import type { FoldedField, ManualField } from '@posthog/sdk/stack'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import { WorkerNonce, WorkerRequest, type EvaluationResult, type FoldEdit } from './evaluation'

interface Folded {
    applied: FoldedField[]
    manual: ManualField[]
    edits: FoldEdit[]
}

export async function runStackWorker(message: unknown, runtime: Runtime): Promise<void> {
    const reply = await work(message, runtime).catch((error: unknown) => {
        if (error instanceof HogError && error.hint) {
            return { error: { code: error.code, message: error.message, hint: error.hint } }
        }
        return {
            error: {
                code: 'stack_evaluation_failed',
                message: "hog couldn't evaluate this stack.",
                hint: 'Check that its dependencies are installed and its index.ts exports its definitions.',
            },
        }
    })
    const nonce = WorkerNonce.safeParse(message).data?.nonce
    if (!process.send || nonce === undefined) {
        process.exitCode = 1
        return
    }
    process.send({ ...reply, nonce })
}

async function work(message: unknown, runtime: Runtime): Promise<Folded | z.input<typeof EvaluationResult>> {
    const request = parseOrThrow(WorkerRequest, message, {
        code: 'stack_evaluation_failed',
        hint: 'Run hog diff again and review the changed fields.',
    })
    if (request.operation === 'fold') {
        process.chdir(request.folder)
        return fold(request, runtime)
    }
    process.chdir(request.root)
    return evaluate(request.folder, request.root, runtime)
}

async function evaluate(folder: string, root: string, runtime: Runtime): Promise<z.input<typeof EvaluationResult>> {
    const { loadStack, sortProblems, typeCheckStack } = await import('@posthog/sdk/stack')
    const validator = await runtime.loadApiTools()
    const checked = await typeCheckStack(folder, { root }).catch(() => {
        throw new HogError(
            'stack_type_check_failed',
            "hog couldn't run this stack's TypeScript compiler.",
            'Install a working typescript dependency in the stack and run hog check again.'
        )
    })
    const { description, problems } = await loadStack(folder, { root, validator })
    const allProblems = [...checked.problems, ...problems]
    if (checked.status === 'skipped') {
        allProblems.push({
            code: 'type_check_skipped',
            severity: 'error',
            message:
                checked.reason ?? 'The type check did not run. Check the stack entry file and TypeScript dependency.',
        })
    }
    return {
        typeCheck: {
            status: checked.status,
            compiler: checked.compiler,
            config: checked.config,
            reason: checked.reason,
        },
        description,
        problems: sortProblems(allProblems),
    }
}

// The SDK rewrites files in place, so the worker keeps each file the drift can touch, lets the SDK write, and
// puts every file back. The caller shows the rewrite and writes it only once it is confirmed.
async function fold(
    request: Extract<z.output<typeof WorkerRequest>, { operation: 'fold' }>,
    runtime: Runtime
): Promise<Folded> {
    const kept = new Map<string, string>()
    for (const file of request.files) {
        if (await runtime.exists(file)) {
            kept.set(file, await runtime.readFile(file))
        }
    }
    const restore = async (): Promise<FoldEdit[]> => {
        const edits = []
        for (const [target, before] of kept) {
            const after = await runtime.readFile(target)
            if (after !== before) {
                await runtime.replaceFile(target, before)
                edits.push({ target, before, after })
            }
        }
        return edits
    }
    const failed = (): HogError =>
        new HogError(
            'stack_fold_failed',
            'Could not work out the changed fields for the definitions.',
            'Check the stack files and run hog diff to review the remaining changes.'
        )
    let folded
    try {
        const { foldDrift } = await import('@posthog/sdk/stack')
        folded = await foldDrift(request.folder, request.drift)
    } catch {
        await restore().catch(() => {})
        throw failed()
    }
    const edits = await restore()
    if (folded.applied.some((field) => !kept.has(join(request.root, field.file)))) {
        throw failed()
    }
    return { ...folded, edits }
}
