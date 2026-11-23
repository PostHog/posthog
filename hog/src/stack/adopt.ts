import { createHash } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'

import type { ResourceDescription } from '@posthog/sdk/stack'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'

import { checkStack } from './check'
import type { ResolvedStack } from './config'
import { fileEdits, insideFolder, previewEdits, undoEdits, writeEdits } from './files'
import type { Adoptable, StackService } from './service'

interface Selection {
    resource: ResourceDescription
    binding: { kind: string; key: string; entity_id: string }
}

interface AdoptionPreview {
    status: 'preview'
    bindings: Selection['binding'][]
    files: string[]
    changes: string[]
}

interface AdoptionOutcome {
    status: 'cancelled' | 'adopted'
    bindings: Selection['binding'][]
    files: string[]
}

function select(entity: Adoptable, naturalKey: string | undefined): Selection {
    const { kind, entity_id, name, body } = entity
    const key = naturalKey
        ? body[naturalKey]
        : name
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, '-')
              .replace(/^-|-$/g, '')
              .slice(0, 100)
    if (typeof key !== 'string' || !key) {
        throw new HogError(
            'adoption_key_missing',
            'An entity has no usable definition key.',
            'Give the entity a name in PostHog, then run pull again.'
        )
    }
    return { resource: { kind, key, body }, binding: { kind, key, entity_id } }
}

function identity({ kind, key }: Pick<ResourceDescription, 'kind' | 'key'>): string {
    return `${kind}:${key}`
}

export async function adopt(
    ctx: Context,
    stack: ResolvedStack,
    service: StackService,
    entities: Adoptable[],
    options: { yes?: boolean; dryRun?: boolean }
): Promise<AdoptionPreview | AdoptionOutcome> {
    const folder = await insideFolder(ctx.runtime, stack.configRoot, stack.dir, true)
    const sdk = await ctx.runtime.stackDefinitions()
    const selected = entities.map((entity) => select(entity, sdk.naturalKey(entity.kind)))
    const bindings = selected.map(({ binding }) => binding)
    if (new Set(bindings.map(identity)).size !== bindings.length) {
        throw new HogError(
            'adoption_key_conflict',
            'Two entities would have the same definition key.',
            'Give the entities distinct names in PostHog and select them again.',
            EXIT_USAGE
        )
    }
    const before = await checkStack(ctx, stack)
    if (!before.ok) {
        throw new HogError(
            'stack_check_failed',
            'The current definitions failed check.',
            'Run hog check and fix the problems before adopting entities.'
        )
    }
    const existing = new Map(before.description.resources.map((item) => [identity(item), item]))
    const missing = selected.flatMap(({ resource }) => {
        const current = existing.get(identity(resource))
        if (current && !isDeepStrictEqual(current.body, resource.body)) {
            throw new HogError(
                'adoption_key_conflict',
                `The definition ${resource.kind} ${resource.key} already has different fields.`,
                'Choose another key for the local definition or review its fields before adopting.'
            )
        }
        return current ? [] : [resource]
    })
    const generated = missing.length ? sdk.generateDefinitions(missing, { existingKeys: existing.keys() }) : []
    let edits = await fileEdits(ctx.runtime, folder, generated, true)
    if (edits.some((edit) => edit.before !== undefined && edit.path !== 'index.ts')) {
        const keys = bindings.map(identity).sort()
        const digest = createHash('sha256').update(JSON.stringify(keys)).digest('hex').slice(0, 16)
        const prefix = `adopted/${digest}`
        edits = await fileEdits(
            ctx.runtime,
            folder,
            [
                ...generated.map((file) => ({ ...file, path: `${prefix}/${file.path}` })),
                { path: 'index.ts', contents: `export * from './${prefix}/index'\n` },
            ],
            true
        )
    }
    const files = edits.map((edit) => edit.path)
    if (options.dryRun) {
        return { status: 'preview' as const, bindings, files, changes: await previewEdits(edits) }
    }
    if (!options.yes) {
        if (!ctx.prompts) {
            throw new HogError(
                'confirmation_required',
                'Review the files and bindings before adopting these entities.',
                'Pass --dry-run to see the changes, then --yes to make them.',
                EXIT_USAGE
            )
        }
        const changes = await previewEdits(edits)
        const labels = bindings.map((item) => escapeControls(`Adopt ${item.kind} ${item.key} (${item.entity_id})`))
        ctx.prompts.note([...changes, ...labels].join('\n'), 'Changes')
        if (!(await ctx.prompts.confirm('Write the definitions and record their bindings?', { initialValue: false }))) {
            return { status: 'cancelled' as const, bindings: [], files: [] }
        }
    }
    await service.prepareAdopt()
    await writeEdits(ctx.runtime, edits)
    try {
        const after = edits.length ? await checkStack(ctx, stack) : before
        const expected = [...before.description.resources, ...missing]
        const checked = new Map(after.description.resources.map((item) => [identity(item), item.body]))
        const matches =
            checked.size === expected.length &&
            expected.every((resource) => isDeepStrictEqual(checked.get(identity(resource)), resource.body))
        if (!after.ok || !matches) {
            throw new HogError(
                'adoption_check_failed',
                'The generated files did not preserve the selected and existing definitions.',
                'Review the local exports and entity fields, then run pull again.'
            )
        }
    } catch (error) {
        await undoEdits(ctx.runtime, edits)
        throw error
    }
    await service.adopt(bindings)
    return { status: 'adopted' as const, bindings, files }
}
