import { z } from 'zod'

import type { CapturedOutput } from '@/core/errors'

const Source = z.object({ file: z.string(), export: z.string().optional() })

export const Description = z.object({
    version: z.literal(1),
    resources: z.array(
        z.object({
            kind: z.string(),
            key: z.string(),
            body: z.record(z.string(), z.json()),
            source: Source.optional(),
            // Definitions this one names by a string, which PostHog creates first.
            depends_on: z.array(z.object({ kind: z.string(), key: z.string() })).optional(),
        })
    ),
})

const Problem = z.object({
    code: z.string(),
    severity: z.enum(['error', 'warning']),
    message: z.string(),
    kind: z.string().optional(),
    key: z.string().optional(),
    path: z.string().optional(),
    file: z.string().optional(),
    line: z.int().positive().optional(),
})

export const EvaluationResult = z.object({
    description: Description,
    problems: Problem.array(),
    typeCheck: z.object({
        status: z.enum(['passed', 'failed', 'skipped']),
        compiler: z.string().optional(),
        config: z.string().optional(),
        reason: z.string().optional(),
    }),
})

export interface Evaluation extends z.output<typeof EvaluationResult> {
    output: CapturedOutput
}

const Field = z.object({ kind: z.string(), key: z.string(), path: z.string() })
const Values = z.object({ pushed: z.json(), found: z.json() })

export const FoldResult = z.object({
    applied: z.array(Field.extend({ file: z.string(), before: z.json(), after: z.json() })),
    manual: z.array(Field.extend({ ...Values.shape, file: z.string().optional(), reason: z.string() })),
    // The rewritten files. The worker puts every file back, so nothing changes until the caller writes these.
    edits: z.array(z.object({ target: z.string(), before: z.string(), after: z.string() })),
})

const Folder = z.string().min(1)
const Foldable = z
    .object({
        kind: z.string(),
        key: z.string(),
        deleted: z.literal(true).optional(),
        fields: z.array(Values.extend({ path: z.string(), sensitive: z.boolean().optional() })),
    })
    .refine((item) => !item.deleted && item.fields.every((field) => !field.sensitive))

export type FoldEdit = z.output<typeof FoldResult>['edits'][number]

const Nonce = z.string().min(1)
export const WorkerRequest = z.discriminatedUnion('operation', [
    z.object({ operation: z.literal('check'), folder: Folder, root: Folder, nonce: Nonce }),
    z.object({
        operation: z.literal('fold'),
        folder: Folder,
        root: Folder,
        files: z.array(Folder),
        drift: z.array(Foldable),
        nonce: Nonce,
    }),
])
export const WorkerNonce = z.object({ nonce: Nonce })
export const WorkerReady = z.object({ ready: z.literal(true) })
export const WorkerFailure = z.object({ error: z.object({ code: z.string(), message: z.string(), hint: z.string() }) })
