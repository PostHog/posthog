import { z } from 'zod'

import type { LearnResult, SkillAssetStatus, SkillsError } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { plural } from '@/core/text'

const LineRange = z.string().regex(/^[1-9]\d*:[1-9]\d*$/, { error: 'Give the lines as <start>:<end>, such as 10:40.' })

const ASSET_NAMES: Record<SkillAssetStatus['name'], string> = {
    'product-skills': 'the PostHog product skills',
    'context-mill': 'the setup skills, such as posthog:instrument-integration',
}

// The MCP exec tool reads one command string after `learn`. hog gets `-s`, `-d` and `--lines` as
// options, so this puts them back where that grammar expects them.
function learnWords(
    words: readonly string[],
    options: { search?: string; describe?: boolean; lines?: string }
): readonly string[] {
    const { search, describe, lines } = options
    if ([search !== undefined, describe === true, lines !== undefined].filter(Boolean).length > 1) {
        throw new HogError(
            'invalid_learn_command',
            'Pass only one of --search, --describe and --lines.',
            'Run `hog learn` to see how each one works.',
            EXIT_USAGE
        )
    }
    if (describe) {
        return ['-d', ...words]
    }
    if (lines !== undefined) {
        return [...words, '--lines', lines]
    }
    if (search !== undefined) {
        // Unquoted keywords after the first one arrive as arguments, as `replay` in `hog learn -s
        // session replay`. They belong to the query, which takes the place of a file search's path.
        return words[0]?.includes(':')
            ? [...words.slice(0, 2), '-s', search, ...words.slice(2)]
            : ['-s', search, ...words]
    }
    return words
}

// The codes `learn` returns, except `offline`, whose message lists the downloads that failed. A
// library built from another revision can return a code this map lacks, which keeps its own code.
const ERRORS: Partial<Record<SkillsError['code'], { code: string; hint: string; exitCode?: number }>> = {
    unknown_skill: { code: 'unknown_skill', hint: 'Run `hog learn skills` to list every skill.' },
    unknown_topic: { code: 'unknown_topic', hint: 'Run `hog learn skills` to list every skill.' },
    unknown_file: {
        code: 'unknown_file',
        hint: 'Give the path from the skill folder, such as references/COMMANDMENTS.md.',
    },
    unavailable: { code: 'skills_unavailable', hint: 'Run `hog learn skills` to list the skills hog serves.' },
    usage: { code: 'invalid_learn_command', hint: 'Run `hog learn` to see the commands.', exitCode: EXIT_USAGE },
}

function toHogError(error: SkillsError): HogError {
    if (error.code === 'offline') {
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
    const { code, hint, exitCode } = ERRORS[error.code] ?? {
        code: error.code,
        hint: 'Run `hog learn` to see the commands.',
    }
    return new HogError(code, error.message, hint, exitCode)
}

// A person sees why the skills may be out of date before the skills themselves.
function notices(out: Output, assets: readonly SkillAssetStatus[]): void {
    for (const asset of assets) {
        const outcome =
            asset.origin === 'cache' && asset.fetchedAt
                ? `so these come from the copy saved on ${asset.fetchedAt.slice(0, 16).replace('T', ' ')} UTC`
                : asset.origin === 'unavailable'
                  ? 'and has no saved copy, so they are missing'
                  : undefined
        if (outcome) {
            const failure = escapeControls(asset.failure ?? '')
            out.line(out.style(`hog couldn't download ${ASSET_NAMES[asset.name]} (${failure}), ${outcome}.`, 'yellow'))
        }
    }
}

export default defineCommand({
    description: 'Read the PostHog agent skills, the step-by-step guides for PostHog tasks',
    args: {
        words: {
            description:
                'A skill such as posthog:instrument-integration, then paths of files in it. `skills` lists every skill',
            optional: true,
            variadic: true,
        },
    },
    options: {
        search: {
            type: 'string',
            short: 's',
            placeholder: 'keywords',
            description: 'Find skills by keywords, or search one file when a skill and its path come first',
        },
        describe: { type: 'boolean', short: 'd', description: 'Show what each skill named is for, without reading it' },
        lines: {
            type: 'string',
            placeholder: 'start:end',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(LineRange, raw, failure),
            description: 'Read only these lines of a file',
        },
    },
    notes: 'Skills are public, so `hog learn` needs no login. hog downloads the latest skills every time, and uses the copy it saved in ~/.posthog/skills only when the download fails.',
    examples: [
        'hog learn skills',
        'hog learn -s "session replay"',
        'hog learn posthog:instrument-integration',
        'hog learn posthog:instrument-integration references/COMMANDMENTS.md',
        'hog learn posthog:instrument-integration references/django.md -s middleware',
        'hog learn posthog:instrument-integration references/django.md --lines 1:40',
    ],

    async run({ args, options, ctx }): Promise<LearnResult> {
        const words = learnWords(args.words ?? [], options)
        const library = await ctx.skills()
        const result = await library.learn(words)
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
        notices(out, result.assets)
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
