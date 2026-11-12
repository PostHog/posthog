import type { CatalogSkill, SkillAssetStatus, SkillKind } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import { plural } from '@/core/text'

import { downloadWarnings, skillsError } from './shared'

interface SkillsList {
    skills: CatalogSkill[]
    assets: SkillAssetStatus[]
}

const KINDS: readonly SkillKind[] = ['learning', 'implementation']

const KIND_TITLES: Record<SkillKind, string> = {
    learning: 'Skills for using PostHog',
    implementation: 'Skills for adding PostHog to your code',
}

export default defineCommand({
    description: 'List every PostHog skill, for using PostHog and for adding it to your code',
    notes: 'Skills are public, so `hog skills list` needs no login.',
    examples: ['hog skills list'],

    async run({ ctx }): Promise<SkillsList> {
        const result = await (await ctx.skills()).catalog()
        if (!result.ok) {
            throw skillsError(result.error)
        }

        return { skills: result.value.skills, assets: result.value.assets }
    },

    human({ result, out }) {
        for (const kind of KINDS) {
            const skills = result.skills.filter((skill) => skill.kind === kind)
            if (skills.length === 0) {
                continue
            }

            out.line(out.style(`${KIND_TITLES[kind]} (${skills.length})`, 'bold'))
            out.table(
                ['skill', 'description'],
                skills.map((skill) => [skill.name, skill.description])
            )
            out.line()
        }

        out.line(
            `${plural(result.skills.length, 'skill')}. Read one with ${out.style('hog skills read <skill>', 'bold')}, or add it to this repository with ${out.style('hog skills add <skill...>', 'bold')}.`
        )
        out.notes({ warnings: downloadWarnings(result.assets) })
    },

    // Names only, grouped by kind, so the whole list stays small enough for an agent's context.
    // `hog skills search` returns descriptions. A download that fell back to the saved copy is reported.
    agent({ result, out }) {
        const stale = result.assets.filter((asset) => asset.origin !== 'network')
        out.json({
            ...Object.fromEntries(
                KINDS.map((kind) => [
                    kind,
                    result.skills.filter((skill) => skill.kind === kind).map((skill) => skill.name),
                ])
            ),
            ...(stale.length > 0 ? { assets: stale } : {}),
        })
    },

    telemetry({ result }) {
        return {
            skill_count: result.skills.length,
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
