import { relative, resolve } from 'node:path'

import { defineCommand } from '@/core/command'
import { EXIT_CHANGES, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { checkStack } from '@/stack/check'
import { resolveStack, stackOptions } from '@/stack/config'
import { selectorFlags } from '@/stack/diff'
import { fileEdits, insideFolder, previewEdits, writeEdits } from '@/stack/files'
import { generateModule, languages } from '@/stack/service'

function quote(value: string): string {
    return /^[\w./-]+$/.test(value) ? value : `'${value.replaceAll("'", "'\\''")}'`
}

export default defineCommand({
    description: 'Write a typed module of the events this stack defines, for Python, Go or TypeScript',
    options: {
        ...stackOptions,
        language: {
            type: 'string',
            placeholder: 'language',
            choices: languages,
            description: 'The language of the module',
        },
        out: { type: 'string', placeholder: 'file', description: 'The file to write, inside this repository' },
        check: {
            type: 'boolean',
            description: 'Write nothing, and exit with 5 when the file differs from the module the stack generates',
        },
        dryRun: { type: 'boolean', description: 'Show what would change without writing' },
        yes: { type: 'boolean', short: 'y', description: 'Replace a file that differs without asking' },
    },
    scopes: ['stack:read'],
    writes: true,
    notes: "PostHog builds the module from the stack's definitions and stores nothing. Run it after the definitions change, and use --check in CI to catch a stale module.",
    examples: [
        'hog stack generate --language python --out app/analytics/events.py',
        'hog stack generate --language golang --out events/events.go --check',
    ],

    async run({ ctx, options }) {
        if (!options.language || !options.out) {
            throw new HogError(
                'generate_options_required',
                'This command needs a language and a file to write.',
                'Pass --language python, golang or typescript, and --out with the file path.',
                EXIT_USAGE
            )
        }
        const stack = await resolveStack(ctx, options.stack, options.env)
        const target = resolve(ctx.runtime.cwd(), options.out)
        const path = relative(stack.root, target).split('\\').join('/')
        // Checked before PostHog is asked, so a path outside the repository fails at once.
        await insideFolder(ctx.runtime, stack.root, path).catch((error: unknown) => {
            throw error instanceof HogError && error.code === 'stack_path_outside'
                ? new HogError(
                      'generate_path_outside',
                      `${options.out!} is outside this repository.`,
                      'Pass --out with a file inside the repository, and check that no folder on the way links outside it.',
                      EXIT_USAGE
                  )
                : error
        })
        const checked = await checkStack(ctx, stack)
        if (!checked.ok) {
            throw new HogError(
                'stack_check_failed',
                'The definitions failed check.',
                'Run hog check and fix the problems, then generate the module again.'
            )
        }
        const module = await generateModule(ctx, stack, checked.description, options.language)
        const edits = await fileEdits(ctx.runtime, stack.root, [{ path, contents: module.content }])
        const summary = {
            path,
            language: module.language,
            eventCount: module.event_count,
            schemaHash: module.schema_hash,
            generatorVersion: module.generator_version,
        }
        const rerun = `hog stack generate --language ${options.language} --out ${quote(options.out)}${selectorFlags(stack)}`
        if (options.check) {
            return edits.length
                ? { status: 'stale' as const, ...summary, next: rerun }
                : { status: 'current' as const, ...summary }
        }
        if (!edits.length) {
            return { status: 'unchanged' as const, ...summary }
        }
        const edit = edits[0]!
        if (edit.before !== undefined && (options.dryRun || !options.yes)) {
            const changes = await previewEdits(edits)
            if (options.dryRun || !ctx.prompts) {
                return { status: 'proposed' as const, ...summary, changes, next: `${rerun} --yes` }
            }
            ctx.prompts.note(changes.join('\n'), 'Changes')
            if (!(await ctx.prompts.confirm(`Replace ${path}?`, { initialValue: false }))) {
                return { status: 'cancelled' as const, ...summary }
            }
        } else if (options.dryRun) {
            return { status: 'proposed' as const, ...summary, changes: [`Create ${escapeControls(path)}`], next: rerun }
        }
        await writeEdits(ctx.runtime, edits)
        return { status: edit.before === undefined ? ('created' as const) : ('updated' as const), ...summary }
    },

    human({ result, out }) {
        const file = escapeControls(result.path)
        const events = `${result.eventCount} ${result.eventCount === 1 ? 'event' : 'events'} in ${result.language}`
        switch (result.status) {
            case 'current':
                out.report({ result: `${file} matches the stack`, status: 'unchanged', effects: [events] })
                break
            case 'stale':
                out.report({
                    result: `${file} differs from the module the stack generates`,
                    status: 'failed',
                    notes: [`Run ${escapeControls(result.next)} to update it.`],
                })
                break
            case 'unchanged':
                out.report({ result: `${file} is already up to date`, status: 'unchanged', effects: [events] })
                break
            case 'proposed':
                out.report({
                    result: `Would write ${file}`,
                    status: 'unchanged',
                    effects: [...result.changes, events],
                    notes: [`Run ${escapeControls(result.next)} to write it.`],
                })
                break
            case 'cancelled':
                out.report({ result: `Kept ${file} as it was`, status: 'unchanged' })
                break
            default:
                out.report({
                    result: `${result.status === 'created' ? 'Created' : 'Updated'} ${file}`,
                    effects: [events],
                })
        }
    },
    agent: ({ result, out }) => out.json(result, { first: ['status', 'path'] }),
    exitCode: (result) => (result.status === 'stale' ? EXIT_CHANGES : EXIT_SUCCESS),
})
