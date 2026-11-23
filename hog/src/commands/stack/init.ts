import { isDeepStrictEqual } from 'node:util'
import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { CONFIG_FILE, configEdit } from '@/core/config'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { findGitRoot } from '@/core/paths'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { REGIONS } from '@/posthog/host'
import { blockEdits } from '@/setup/agents-md'
import { DEFAULT_STACK_DIR, resolveStack, StackName, stackOptions, StacksConfig } from '@/stack/config'
import { displayPath, fileEdits, insideFolder, previewEdits, writeEdits } from '@/stack/files'
import { scaffold } from '@/stack/scaffold'

const ProjectNumber = z
    .string()
    .regex(/^[1-9]\d*$/)
    .transform(Number)
    .pipe(z.int().positive())
const projectNumber = (value: string, failure: ParseFailure): number =>
    parseOrThrow(ProjectNumber, value, { ...failure, hint: 'Pass the project number from its PostHog URL.' })

export default defineCommand({
    description: 'Create a stack folder and add it to posthog.json',
    scopes: [],
    writes: true,
    options: {
        ...stackOptions,
        dir: {
            type: 'string',
            placeholder: 'folder',
            description: 'The folder for definitions, relative to posthog.json. Defaults to posthog',
        },
        project: {
            type: 'string',
            placeholder: 'id',
            parse: projectNumber,
            description: 'The project for this environment. Defaults to the project in posthog.json',
        },
        dryRun: { type: 'boolean', description: 'Show which files would change' },
        yes: { type: 'boolean', description: 'Replace conflicting starter files after reviewing --dry-run' },
    },
    examples: [
        'hog init --stack web',
        'hog init --stack web --env production --project 2 --host https://eu.posthog.com',
    ],

    async run({ ctx, options }) {
        const loaded = await ctx.config()
        const root = loaded?.root ?? (await findGitRoot(ctx.runtime))?.root ?? ctx.runtime.cwd()
        const configured = loaded?.config.stacks ?? {}
        const names = Object.keys(configured)
        const input =
            options.stack ?? (names.length === 1 ? names[0] : await ctx.prompts?.text('What is the stack called?'))
        if (!input) {
            throw new HogError(
                'stack_required',
                'Choose a name for the stack.',
                'Run `hog init --stack <name>`.',
                EXIT_USAGE
            )
        }
        const name = parseOrThrow(StackName, input, {
            code: 'invalid_stack',
            hint: 'Pass --stack with a lowercase name, such as web.',
            exitCode: EXIT_USAGE,
        })
        const existing = Object.hasOwn(configured, name) ? configured[name] : undefined
        if (existing) {
            await resolveStack(ctx, name, options.env)
            return { status: 'existing' as const, stack: name, dir: existing.dir, files: [] }
        }
        if (name.length > 100 || ['bindings', 'adoptable'].includes(name)) {
            throw new HogError(
                'invalid_stack_name',
                'PostHog cannot use this stack name.',
                'Choose a name up to 100 characters other than bindings or adoptable.',
                EXIT_USAGE
            )
        }
        const path = await insideFolder(ctx.runtime, root, options.dir ?? DEFAULT_STACK_DIR)
        const dir = displayPath(await ctx.runtime.realPath(root), path)
        if (Object.values(configured).some((other) => other.dir === dir)) {
            throw new HogError(
                'stack_folder_used',
                'Another stack already uses this folder.',
                'Pass --dir with a different folder.',
                EXIT_USAGE
            )
        }
        const configuredProject = ctx.runtime.env.HOG_PROJECT_ID ?? loaded?.config.projectId
        const project =
            options.project ??
            (configuredProject === undefined
                ? undefined
                : projectNumber(String(configuredProject), { code: 'invalid_project', exitCode: EXIT_USAGE }))
        if (options.env && project === undefined) {
            throw new HogError(
                'stack_project_required',
                'An environment needs a PostHog project.',
                'Pass --project with the project number.',
                EXIT_USAGE
            )
        }
        const host = ctx.globals.host ?? loaded?.config.host ?? REGIONS.us
        const stack =
            project === undefined
                ? { dir }
                : { dir, environments: { [options.env ?? 'production']: { project, host } } }
        const stacks = { ...configured, [name]: stack }
        const target = await insideFolder(ctx.runtime, root, CONFIG_FILE)
        const config = await configEdit(ctx.runtime, target, (raw) => {
            const current =
                parseOrThrow(StacksConfig.optional(), raw.stacks, {
                    code: 'invalid_config',
                    hint: 'Review posthog.json and run hog config check.',
                }) ?? {}
            if (!isDeepStrictEqual(current, configured)) {
                throw new HogError(
                    'stack_config_changed',
                    'The stack configuration changed while hog was reading it.',
                    'Review posthog.json before running init again.'
                )
            }
            raw.stacks = stacks
        })
        const starters = (await fileEdits(ctx.runtime, path, scaffold())).map((edit) => ({
            ...edit,
            path: `${dir}/${edit.path}`,
        }))
        const guides = (await blockEdits(ctx.runtime, root, undefined, stacks))
            .filter((edit) => edit.status !== 'unchanged')
            .map((edit) => ({ ...edit, path: displayPath(root, edit.path) }))
        const edits = [...starters, ...guides, { ...config, target, path: CONFIG_FILE }]
        if (new Set(edits.map((edit) => edit.target)).size !== edits.length) {
            throw new HogError(
                'stack_file_overlap',
                'Two stack files point to the same file.',
                'Give each file its own path and check the links before retrying.',
                EXIT_USAGE
            )
        }
        const conflicts = starters.filter((edit) => edit.before !== undefined)
        const files = edits.map((edit) => edit.path)
        if (options.dryRun) {
            return { status: 'preview' as const, stack: name, dir, files, changes: await previewEdits(conflicts) }
        }
        if (conflicts.length && !options.yes) {
            if (!ctx.prompts) {
                throw new HogError(
                    'confirmation_required',
                    'The stack folder contains files that would change.',
                    'Review `hog init --dry-run`, then pass --yes to replace those files.',
                    EXIT_USAGE
                )
            }
            ctx.prompts.note((await previewEdits(conflicts)).join('\n'), 'Files to replace')
            if (!(await ctx.prompts.confirm('Replace these files?', { initialValue: false }))) {
                return { status: 'cancelled' as const, stack: name, dir, files: [] }
            }
        }
        await writeEdits(ctx.runtime, edits)
        return { status: 'created' as const, stack: name, dir, files }
    },
    human({ result, out }) {
        const title = {
            existing: 'Already configured',
            created: 'Created',
            cancelled: 'Cancelled setup for',
            preview: 'Would create',
        }[result.status]
        out.report({
            result: `${title} stack ${result.stack} in ${escapeControls(result.dir)}`,
            status: result.status === 'created' ? 'done' : 'unchanged',
            effects: [...result.files.map(escapeControls), ...(result.changes ?? [])],
            notes:
                result.status === 'created'
                    ? [
                          `Run \`npm install\` in ${escapeControls(result.dir)} and commit its package-lock.json, then run \`hog check --stack ${result.stack}\`. The pull request workflow installs the folder with npm ci.`,
                      ]
                    : [],
        })
    },
    agent: ({ result, out }) => out.json(result),
})
