import type { ResourceDescription } from '@posthog/sdk/stack'

import { HogError, type CapturedOutput } from '@/core/errors'

import type { FoldEdit } from './evaluation'
import type { GeneratedFile } from './files'
import type { Diff } from './service'

export interface FoldedField {
    file?: string
    kind?: string
    key?: string
    path: string
    pushed: unknown
    found: unknown
    reason?: string
}

export interface FoldResult {
    applied: FoldedField[]
    manual: FoldedField[]
    output?: CapturedOutput
}

export interface FoldProposal extends FoldResult {
    edits: FoldEdit[]
}

export interface StackDefinitions {
    naturalKey(kind: string): string | undefined
    generateDefinitions(resources: ResourceDescription[], options?: { existingKeys: Iterable<string> }): GeneratedFile[]
    // Works out the rewrite and leaves every file as it was.
    foldDrift(dir: string, drift: Diff['drift'], files: { root: string; targets: string[] }): Promise<FoldProposal>
}

export async function loadDefinitions(fromSource: boolean): Promise<StackDefinitions> {
    const sdk = await import('@posthog/sdk/stack')
    return {
        naturalKey: (kind) => sdk.kindSpec(kind)?.naturalKey?.field,
        generateDefinitions(resources, options) {
            try {
                return sdk.generateDefinitions(resources, options)
            } catch {
                throw new HogError(
                    'stack_generation_failed',
                    'Could not generate definitions for these entities.',
                    'Check that the SDK supports the kind and review the entity fields.'
                )
            }
        },
        async foldDrift(dir, drift, files) {
            const { foldInChild } = await import('./child')
            const result = await foldInChild(dir, drift, fromSource, files)
            return {
                applied: result.applied.map(({ before, after, ...field }) => ({
                    ...field,
                    pushed: before,
                    found: after,
                })),
                manual: result.manual,
                edits: result.edits,
                ...(result.output.stdout || result.output.stderr ? { output: result.output } : {}),
            }
        },
    }
}
