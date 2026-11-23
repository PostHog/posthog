import { join } from 'node:path'

import type { StackDescription } from '@posthog/sdk/stack'

import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'

import { checkStack } from './check'
import type { ResolvedStack } from './config'
import type { FoldedField, FoldResult } from './definitions'
import { displayPath, insideFolder, type FileEdit } from './files'
import { HiddenValuesNote, type Diff } from './service'

export async function pullDrift(
    ctx: Context,
    stack: ResolvedStack,
    folder: string,
    drift: Diff['drift'],
    description?: StackDescription
): Promise<FoldResult & { edits: FileEdit[] }> {
    const manual: FoldedField[] = []
    if (!drift.length) {
        return { applied: [], manual, edits: [] }
    }
    if (!description) {
        const check = await checkStack(ctx, stack)
        if (!check.ok) {
            throw new HogError(
                'stack_check_failed',
                'The local definitions have changed or could not be checked.',
                'Run hog check before pulling drift.'
            )
        }
        description = check.description
    }
    const locations = new Map(
        description.resources.map((item) => [JSON.stringify([item.kind, item.key]), item.source?.file])
    )
    const keysByFile = new Set<string>()
    const ambiguous = new Set<string>()
    for (const item of description.resources) {
        const locator = JSON.stringify([item.source?.file, item.key])
        if (keysByFile.has(locator)) {
            ambiguous.add(locator)
        }
        keysByFile.add(locator)
    }

    const toFold: Diff['drift'] = []
    for (const item of drift) {
        const file = locations.get(JSON.stringify([item.kind, item.key]))
        const location = { kind: item.kind, key: item.key, file }
        if (item.deleted) {
            manual.push({ ...location, path: 'binding', pushed: 'Present', found: 'Removed' })
            continue
        }
        const fields = []
        for (const field of item.fields) {
            if (field.sensitive || field.hidden) {
                manual.push({
                    ...location,
                    path: field.path,
                    pushed: '(hidden)',
                    found: '(hidden)',
                    reason: HiddenValuesNote,
                })
            } else if (ambiguous.has(JSON.stringify([file, item.key]))) {
                manual.push({ ...location, ...field, reason: 'Several definitions in this file use this key.' })
            } else {
                fields.push(field)
            }
        }
        if (fields.length) {
            toFold.push({ ...item, fields })
        }
    }
    if (!toFold.length) {
        return { applied: [], manual, edits: [] }
    }
    const files = new Set(toFold.flatMap((item) => locations.get(JSON.stringify([item.kind, item.key])) ?? []))
    const targets: string[] = []
    for (const file of files) {
        await insideFolder(ctx.runtime, stack.root, file)
        targets.push(join(stack.root, file))
    }
    const sdk = await ctx.runtime.stackDefinitions()
    const { edits, ...folded } = await sdk.foldDrift(folder, toFold, { root: stack.root, targets })
    return {
        ...folded,
        manual: [...folded.manual, ...manual],
        edits: edits.map(({ target, before, after }) => ({
            path: displayPath(stack.root, target),
            target,
            before,
            contents: after,
        })),
    }
}
