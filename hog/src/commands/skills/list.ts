import type { SkillAssetStatus } from '@posthog/mcp/src/cli/library-types'

import { printDownloadWarnings } from '@/commands/learn'
import { defineCommand } from '@/core/command'
import { plural } from '@/core/text'

import { skillsError } from './shared'

interface SkillsList {
    skills: { id: string; name: string; description: string }[]
    assets: SkillAssetStatus[]
}

export default defineCommand({
    description: 'List the PostHog skills you can add to this repository',
    notes: 'Skills are public, so `hog skills list` needs no login.',
    examples: ['hog skills list'],

    async run({ ctx }): Promise<SkillsList> {
        const result = await (await ctx.skills()).installable()
        if (!result.ok) {
            throw skillsError(result.error)
        }

        const skills = result.value.skills.map(({ id, name, description }) => ({
            id,
            name,
            description: description.trim().split('\n')[0] ?? '',
        }))

        return { skills, assets: result.value.assets }
    },

    human({ result, out }) {
        printDownloadWarnings(out, result.assets)

        out.table(
            ['id', 'name', 'description'],
            result.skills.map((skill) => [skill.id, skill.name, skill.description])
        )

        out.line(
            out.style(
                `${plural(result.skills.length, 'skill')}. Run \`hog skills add <id...>\` to add them to this repository.`,
                'dim'
            )
        )
    },

    agent({ result, out }) {
        out.json(result)
    },

    telemetry({ result }) {
        return {
            skill_count: result.skills.length,
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
