import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, outputNotes } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { adopt } from '@/stack/adopt'
import { resolveStack, stackOptions } from '@/stack/config'
import type { FoldedField } from '@/stack/definitions'
import { pollDiff, selectorFlags, startCheckedDiff } from '@/stack/diff'
import { pullDrift } from '@/stack/drift'
import { insideFolder, previewEdits, writeEdits } from '@/stack/files'
import { stackService, waitOption } from '@/stack/service'

const Kind = z.string().regex(/^[a-z][a-z0-9_]*$/, 'Use a definition kind such as flag or action.')
const PageSize = z.string().regex(/^\d+$/).transform(Number).pipe(z.int().min(1).max(100))
const Cursor = z.string().min(1).max(2000)

function fieldText(field: FoldedField): string {
    const where = field.file ?? [field.kind, field.key].filter(Boolean).join(' ')
    const reason = field.reason ? ` (${field.reason})` : ''
    return escapeControls(
        `${where}  ${field.path}  ${JSON.stringify(field.pushed)} → ${JSON.stringify(field.found)}${reason}`
    )
}

const DRIFT_REMAINS =
    'hog diff keeps showing this drift until the next push records the rewritten values, because PostHog compares with what was last pushed.'

export default defineCommand({
    description: 'Bring drift into definitions or adopt existing entities',
    args: { entities: { optional: true, variadic: true, description: 'The IDs or names to adopt' } },
    options: {
        ...stackOptions,
        adopt: {
            type: 'string',
            placeholder: 'kind',
            scopes: ['stack:write'],
            description: 'List entities available to adopt. Recording a binding also needs stack:write',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(Kind, raw, failure),
        },
        limit: {
            type: 'string',
            placeholder: 'count',
            description: 'The number of entities on a page, up to 100',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(PageSize, raw, failure),
        },
        cursor: {
            type: 'string',
            placeholder: 'cursor',
            description: 'The cursor from the previous page of entities',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(Cursor, raw, failure),
        },
        wait: waitOption,
        dryRun: { type: 'boolean', description: 'Show the changes before writing' },
        yes: {
            type: 'boolean',
            short: 'y',
            description: 'Write the rewritten or adopted definitions, and record bindings, without asking',
        },
    },
    scopes: ['stack:read'],
    writes: true,
    examples: [
        'hog pull',
        'hog pull --yes',
        'hog pull --adopt action',
        'hog pull --adopt action 42 --dry-run',
        'hog pull --adopt action 42 --yes',
    ],
    async run({ ctx, options, args }) {
        const stack = await resolveStack(ctx, options.stack, options.env)
        if (options.adopt) {
            if (options.wait || (args.entities.length && (options.limit !== undefined || options.cursor))) {
                throw new HogError(
                    'usage_error',
                    'Select entities by ID or name, or list a page.',
                    'Use --wait only when pulling drift. List a page with --limit and --cursor.',
                    EXIT_USAGE
                )
            }
            const service = await stackService(ctx, stack)
            if (args.entities.length) {
                return adopt(ctx, stack, service, await service.findAdoptable(options.adopt, args.entities), options)
            }
            const limit = options.limit ?? 100
            const page = await service.adoptable(options.adopt, limit, options.cursor)
            const cursor = page.next?.searchParams.get('cursor') ?? null
            const entities = page.results.map(({ entity_id, name }) => ({ id: entity_id, name }))
            const base = `hog pull --adopt ${options.adopt} --limit ${limit}${selectorFlags(stack)}`
            const next =
                cursor !== null && /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(cursor) ? `${base} --cursor ${cursor}` : null
            if (!ctx.prompts || !entities.length || options.dryRun) {
                return { status: 'listed' as const, entities, next, nextCursor: cursor }
            }
            const choices = entities.map(({ id, name }) => ({ value: id, label: escapeControls(`${name} (${id})`) }))
            const ids = await ctx.prompts.multiselect('Select entities to adopt', choices)
            if (!ids.length) {
                return { status: 'listed' as const, entities, next, nextCursor: cursor }
            }
            return adopt(
                ctx,
                stack,
                service,
                page.results.filter((item) => ids.includes(item.entity_id)),
                options
            )
        }
        if (args.entities.length || options.limit !== undefined || options.cursor) {
            throw new HogError(
                'usage_error',
                'Selecting entities needs a kind.',
                'Pass --adopt <kind> with the IDs or names.',
                EXIT_USAGE
            )
        }
        const folder = await insideFolder(ctx.runtime, stack.configRoot, stack.dir, true)
        const { id, service, description } = options.wait
            ? { id: options.wait, service: await stackService(ctx, stack), description: undefined }
            : await startCheckedDiff(ctx, stack)
        const saved = await pollDiff(ctx, service, id)
        if (saved.status === 'running') {
            return {
                status: 'running' as const,
                id,
                next: `hog pull --wait ${id}${selectorFlags(stack)}${options.dryRun ? ' --dry-run' : ''}`,
            }
        }
        if (options.dryRun) {
            return { status: 'drift' as const, id, drift: saved.diff.drift, notes: saved.diff.notes }
        }
        const { edits, ...fields } = await pullDrift(ctx, stack, folder, saved.diff.drift, description)
        const files = edits.map((edit) => edit.path)
        if (edits.length && !options.yes) {
            const changes = await previewEdits(edits)
            const next = `hog pull --wait ${id}${selectorFlags(stack)} --yes`
            if (!ctx.prompts) {
                return { status: 'proposed' as const, id, ...fields, files, changes, next }
            }
            ctx.prompts.note(changes.join('\n'), 'Changes')
            if (!(await ctx.prompts.confirm('Rewrite these definitions?', { initialValue: false }))) {
                return { status: 'cancelled' as const, operation: 'rewrite' as const, id }
            }
        }
        await writeEdits(ctx.runtime, edits)
        return {
            status: 'pulled' as const,
            id,
            ...fields,
            files,
            ...(fields.applied.length ? { note: DRIFT_REMAINS } : {}),
        }
    },
    human({ result, out }) {
        switch (result.status) {
            case 'listed':
                out.table(
                    ['ID', 'name'],
                    result.entities.map((item) => [item.id, item.name])
                )
                out.notes({
                    notes: result.next
                        ? [result.next]
                        : result.nextCursor
                          ? ['The next page needs --cursor. Read nextCursor from the JSON output.']
                          : [],
                })
                break
            case 'running':
                out.report({ result: 'Still checking for drift', notes: [result.next] })
                break
            case 'drift':
                out.report({
                    result: result.drift.length ? 'Drift in PostHog' : 'No drift in PostHog',
                    status: 'unchanged',
                    effects: result.drift.flatMap((item) => [
                        ...(item.deleted ? [escapeControls(`${item.kind} ${item.key} was removed in PostHog`)] : []),
                        ...item.fields.map((field) =>
                            field.hidden
                                ? escapeControls(`${item.kind} ${item.key}  ${field.path}  (hidden)`)
                                : fieldText({ file: `${item.kind} ${item.key}`, ...field })
                        ),
                    ]),
                    notes: result.notes,
                })
                break
            case 'proposed':
                out.report({
                    result: `Would rewrite ${result.applied.length} fields. ${result.manual.length} need a manual edit.`,
                    status: 'unchanged',
                    effects: [
                        ...result.changes,
                        ...result.applied.map((field) => `Would rewrite  ${fieldText(field)}`),
                    ],
                    warnings: result.manual.map((field) => `Edit  ${fieldText(field)}`),
                    notes: [
                        `Run ${result.next} to write these changes.`,
                        ...(result.output ? outputNotes(result.output) : []),
                    ],
                })
                break
            case 'pulled':
                out.report({
                    result: `Rewrote ${result.applied.length} fields. ${result.manual.length} need a manual edit.`,
                    effects: result.applied.map((field) => `Rewrote  ${fieldText(field)}`),
                    warnings: result.manual.map((field) => `Edit  ${fieldText(field)}`),
                    notes: [
                        ...(result.note ? [result.note] : []),
                        ...(result.output ? outputNotes(result.output) : []),
                    ],
                })
                break
            case 'preview':
                out.report({
                    result: 'Would adopt these entities',
                    status: 'unchanged',
                    effects: [
                        ...result.changes,
                        ...result.bindings.map((item) =>
                            escapeControls(`${item.kind} ${item.key} (${item.entity_id})`)
                        ),
                    ],
                })
                break
            case 'adopted':
                out.report({
                    result: 'Recorded pending bindings',
                    effects: [
                        ...result.bindings.map((item) =>
                            escapeControls(`${item.kind} ${item.key} (${item.entity_id})`)
                        ),
                        ...result.files.map(escapeControls),
                    ],
                    notes: ['Run hog diff to review the bindings before pushing.'],
                })
                break
            case 'cancelled':
                out.report({
                    result: 'operation' in result ? 'Rewrite cancelled' : 'Adoption cancelled',
                    status: 'unchanged',
                })
        }
    },
    agent: ({ result, out }) => out.json(result),
    exitCode: (result) => (result.status === 'running' ? EXIT_PENDING : EXIT_SUCCESS),
})
