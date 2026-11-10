import { z } from 'zod'

import type { LearnRequest, LearnResult, SkillAssetStatus, SkillsError } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { plural } from '@/core/text'

const LineRange = z
    .string()
    .regex(/^[1-9]\d*:[1-9]\d*$/, { error: 'Pass the lines as `<start>:<end>`, such as `10:40`.' })

const ASSET_NAMES: Record<SkillAssetStatus['name'], string> = {
    'product-skills': 'the PostHog product skills',
    'context-mill': 'the setup skills, such as posthog:instrument-integration',
}

function learnRequest(
    skill: string | undefined,
    paths: readonly string[],
    options: { search?: string; describe?: boolean; lines?: string }
): LearnRequest {
    const { search, describe, lines } = options
    const modeCount = Number(search !== undefined) + Number(describe === true) + Number(lines !== undefined)

    if (modeCount > 1) {
        throw new HogError(
            'invalid_learn_command',
            'Pass only one of `--search`, `--describe`, or `--lines`.',
            'Run `hog learn` to see how each one works.',
            EXIT_USAGE
        )
    }

    if (search === undefined) {
        return { skill, paths, describe, lines }
    }

    // Unquoted keywords after the first one arrive as arguments, as `replay` in `hog learn -s session
    // replay`. They belong to the query. A file search keeps its skill and the path after it.
    if (skill?.includes(':')) {
        return { skill, paths: paths.slice(0, 1), search: [search, ...paths.slice(1)].join(' ') }
    }

    return { paths: [], search: [search, ...(skill === undefined ? [] : [skill]), ...paths].join(' ') }
}

const DEFAULT_HINT = 'Run `hog learn` to see the commands.'
const LIST_HINT = 'Run `hog learn skills` to list every skill.'

// `offline` has its own error, whose message lists the downloads that failed.
const ERRORS: Partial<Record<SkillsError['code'], { code?: string; hint?: string; exitCode?: number }>> = {
    unknown_skill: { hint: LIST_HINT },
    unknown_topic: { hint: LIST_HINT },
    unknown_file: { hint: 'Pass the path relative to the skill folder, such as `references/COMMANDMENTS.md`.' },
    unavailable: { code: 'skills_unavailable', hint: 'Run `hog learn skills` to list the skills hog serves.' },
    usage: { code: 'invalid_learn_command', exitCode: EXIT_USAGE },
}

export function offlineError(error: SkillsError): HogError {
    const assets = error.assets ?? []
    const failures = assets.map((asset) => `\n  ${asset.url}: ${asset.failure}`).join('')

    return new HogError(
        'skills_offline',
        `${error.message}${failures}`,
        'Check your internet connection, then run the command again.',
        undefined,
        { assets }
    )
}

function toHogError(error: SkillsError): HogError {
    if (error.code === 'offline') {
        return offlineError(error)
    }

    const { code = error.code, hint = DEFAULT_HINT, exitCode } = ERRORS[error.code] ?? {}
    return new HogError(code, error.message, hint, exitCode)
}

// A person sees why the skills may be out of date before the skills themselves.
export function printDownloadWarnings(out: Output, assets: readonly SkillAssetStatus[]): void {
    for (const asset of assets) {
        const outcome =
            asset.origin === 'cache' && asset.fetchedAt
                ? `. Using the copy saved on ${asset.fetchedAt.slice(0, 16).replace('T', ' ')} UTC`
                : asset.origin === 'unavailable'
                  ? ", and there's no saved copy"
                  : undefined

        if (outcome) {
            const failure = escapeControls(asset.failure ?? '')
            out.line(out.style(`hog couldn't download ${ASSET_NAMES[asset.name]} (${failure})${outcome}.`, 'yellow'))
        }
    }
}

export default defineCommand({
    description: 'Read PostHog agent skills: step-by-step guides for PostHog tasks',
    args: {
        skill: {
            description: 'A skill such as posthog:instrument-integration. `skills` lists every skill',
            optional: true,
        },
        paths: {
            description: 'Paths of files in the skill, such as references/COMMANDMENTS.md',
            optional: true,
            variadic: true,
        },
    },
    options: {
        search: {
            type: 'string',
            short: 's',
            placeholder: 'keywords',
            description: 'Find skills by keyword. With a skill and a path first, search that file instead',
        },
        describe: { type: 'boolean', short: 'd', description: 'Show what each named skill is for, without reading it' },
        lines: {
            type: 'string',
            placeholder: 'start:end',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(LineRange, raw, failure),
            description: 'Read only these lines of a file',
        },
    },
    notes: 'Skills are public, so `hog learn` needs no login. hog downloads the latest skills on every run, and uses the copy saved in `~/.posthog/skills` only when the download fails.',
    examples: [
        'hog learn skills',
        'hog learn -s "session replay"',
        'hog learn posthog:instrument-integration',
        'hog learn posthog:instrument-integration references/COMMANDMENTS.md',
        'hog learn posthog:instrument-integration references/django.md -s middleware',
        'hog learn posthog:instrument-integration references/django.md --lines 1:40',
    ],

    async run({ args, options, ctx }): Promise<LearnResult> {
        const request = learnRequest(args.skill, args.paths ?? [], options)
        const library = await ctx.skills()
        const result = await library.learn(request)

        if (!result.ok) {
            throw toHogError(result.error)
        }

        if (result.value.reads.length > 0) {
            const { recordSkillReads } = await import('@/setup/state')
            await recordSkillReads(ctx, result.value.reads)
        }

        return result.value
    },

    human({ result, out }) {
        printDownloadWarnings(out, result.assets)
        const { output } = result
        switch (output.kind) {
            case 'overview':
                out.line('Commands:')
                for (const command of output.commands) {
                    out.line(`  ${escapeControls(command)}`)
                }
                return
            case 'list':
                for (const skill of output.skills) {
                    out.line(escapeControls(skill))
                }
                out.line(
                    out.style(
                        `${plural(output.count, 'skill')}${output.truncated ? `, ${output.skills.length} listed` : ''}. Run \`hog learn <skill>\` to read one.`,
                        'dim'
                    )
                )
                return
            case 'text':
                out.line(escapeControls(output.text))
        }
    },

    agent({ result, out }) {
        out.json(result)
    },

    // Skill names come from the published catalog, and a read only counts once it served, so these
    // never carry text the caller typed. Search keywords and file paths stay out.
    telemetry({ result }) {
        return {
            learn_kind: result.output.kind,
            skills_read: [...new Set(result.reads.map((read) => `${read.source}:${read.skill}`))].sort(),
            read_kinds: [...new Set(result.reads.map((read) => read.readKind))].sort(),
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
