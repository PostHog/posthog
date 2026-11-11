import type { SkillSearchResult } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { plural } from '@/core/text'

import { toHogError } from './read'
import { downloadWarnings } from './shared'

// A person sees the first matching lines of each skill. An agent gets them all as JSON.
const MATCHES_SHOWN = 3

export default defineCommand({
    description: 'Find PostHog agent skills by keywords',
    args: {
        keywords: { description: 'Words to look for in skill names, descriptions and files', variadic: true },
    },
    notes: 'Every word is a keyword, so no quotes are needed. Skills that match more of the keywords come first. Skills are public, so `hog skills search` needs no login.',
    examples: ['hog skills search session replay', 'hog skills search feature flags react'],

    async run({ args, ctx }): Promise<SkillSearchResult> {
        const library = await ctx.skills()
        const result = await library.search(args.keywords.join(' '))

        if (!result.ok) {
            throw toHogError(result.error)
        }

        return result.value
    },

    human({ result, out }) {
        for (const skill of result.skills) {
            out.line(out.style(skill.name, 'bold'))
            out.line(`  ${escapeControls(skill.description.split('\n')[0] ?? '')}`)
            for (const match of skill.matches.slice(0, MATCHES_SHOWN)) {
                out.line(out.style(`  ${escapeControls(`${match.path}:${match.line}: ${match.text.trim()}`)}`, 'dim'))
            }
            out.line()
        }

        out.line(
            result.skills.length === 0
                ? `No skills matched. See every skill with ${out.style('hog skills list', 'bold')}.`
                : `${plural(result.skills.length, 'skill')}. Read one with ${out.style('hog skills read <skill>', 'bold')}.`
        )
        out.notes({ warnings: downloadWarnings(result.assets) })
    },

    agent({ result, out }) {
        out.json(result)
    },

    // Only the count leaves, because the keywords are text the caller typed.
    telemetry({ result }) {
        return {
            skills_found: result.skills.length,
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
