import { z } from 'zod'

import type { SkillReadResult, SkillsError } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'

import { downloadWarnings, offlineError } from './shared'

const LineRange = z
    .string()
    .regex(/^[1-9]\d*:[1-9]\d*$/, { error: 'Pass the lines as `<start>:<end>`, such as `10:40`.' })

const LIST_HINT = 'Run `hog skills list` to see every skill.'

// `offline` has its own error, whose message lists the downloads that failed.
const ERRORS: Partial<Record<SkillsError['code'], { code?: string; hint?: string; exitCode?: number }>> = {
    unknown_skill: { hint: LIST_HINT },
    unknown_file: { hint: 'Run `hog skills read <skill>` to see the files in the skill.' },
    unavailable: { code: 'skills_unavailable', hint: LIST_HINT },
    usage: {
        code: 'invalid_read_command',
        hint: 'Run `hog skills read --help` to see how to read a skill.',
        exitCode: EXIT_USAGE,
    },
}

export function toHogError(error: SkillsError): HogError {
    if (error.code === 'offline') {
        return offlineError(error)
    }

    const { code = error.code, hint = LIST_HINT, exitCode } = ERRORS[error.code] ?? {}
    return new HogError(code, error.message, hint, exitCode)
}

export default defineCommand({
    description: 'Read a PostHog agent skill, or one file in it',
    args: {
        skill: { description: 'A skill from `hog skills list`, such as instrument-integration' },
    },
    options: {
        file: {
            type: 'string',
            placeholder: 'path',
            description: 'Read this file in the skill instead of SKILL.md, such as references/COMMANDMENTS.md',
        },
        lines: {
            type: 'string',
            placeholder: 'start:end',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(LineRange, raw, failure),
            description: 'Read only these lines, for a file too large to read whole',
        },
    },
    notes: 'Reading a skill shows its SKILL.md and lists its other files. Skills are public, so `hog skills read` needs no login. hog downloads the latest skills on every run, and uses the copy saved in `~/.posthog/skills` only when the download fails.',
    examples: [
        'hog skills read instrument-integration',
        'hog skills read instrument-integration --file references/COMMANDMENTS.md',
        'hog skills read instrument-integration --file references/django.md --lines 1:40',
    ],

    async run({ args, options, ctx }): Promise<SkillReadResult> {
        const library = await ctx.skills()
        const result = await library.read({ skill: args.skill, file: options.file, lines: options.lines })

        if (!result.ok) {
            throw toHogError(result.error)
        }

        const { recordSkillReads } = await import('@/setup/state')
        await recordSkillReads(ctx, result.value.reads)

        return result.value
    },

    human({ result, out }) {
        out.line(escapeControls(result.text))
        out.notes({ warnings: downloadWarnings(result.assets) })
    },

    agent({ result, out }) {
        out.json(result)
    },

    // Skill names come from the published catalog, and a read only counts once it served, so these
    // never carry text the caller typed. File paths stay out.
    telemetry({ result }) {
        return {
            skills_read: [...new Set(result.reads.map((read) => `${read.source}:${read.skill}`))].sort(),
            read_kinds: [...new Set(result.reads.map((read) => read.readKind))].sort(),
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
