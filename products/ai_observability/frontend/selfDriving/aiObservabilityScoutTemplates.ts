import { parse as parseYaml } from 'yaml'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import type { ScoutCreateInitialValues } from 'products/signals/frontend/inbox/logics/scoutCreateModalLogic'
import { scoutTags } from 'products/signals/frontend/inbox/utils/scoutTags'

import costlyUsersSkill from '../../backend/scouts/signals-scout-ai-observability-costly-users.md?raw'
import dailyDigestSkill from '../../backend/scouts/signals-scout-ai-observability-daily-digest.md?raw'
import errorPatternsSkill from '../../backend/scouts/signals-scout-ai-observability-error-patterns.md?raw'

export const AI_OBSERVABILITY_SCOUT_TAG = 'ai-observability'

export type AIObservabilityScoutTemplateKey = 'daily-digest' | 'costly-users' | 'error-patterns'

export interface AIObservabilityScoutTemplate {
    key: AIObservabilityScoutTemplateKey
    title: string
    description: string
    schedule: string
    initialValues: ScoutCreateInitialValues
}

const FRONTMATTER_BLOCK = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/

interface ScoutSkillFrontmatter {
    name?: string
    description?: string
    'scout-tags'?: string[]
}

/** Every template runs daily at 9 a.m. and writes to the inbox. Tags come from the skill file. */
const DAILY_AT_9AM: Omit<NonNullable<ScoutCreateInitialValues['config']>, 'tags'> = {
    enabled: true,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: '0 9 * * *',
}

/**
 * Splits a scout's `SKILL.md` into the fields the create form takes separately. The file is the
 * single source for the scout itself — posthog.com's pocket guides fetch the same one — so
 * everything here is read from it rather than restated.
 *
 * `source` names the file in any throw: all three parse at module scope, so without it a malformed
 * file gives an error nobody can trace back to a filename.
 */
function readScoutSkill(raw: string, source: string): ScoutCreateInitialValues {
    const match = raw.match(FRONTMATTER_BLOCK)
    if (!match) {
        throw new Error(`Scout skill file ${source} is missing its frontmatter`)
    }

    const frontmatter = (parseYaml(match[1]) ?? {}) as ScoutSkillFrontmatter
    const name = frontmatter.name?.trim()
    const description = frontmatter.description?.trim()
    // Explicit emptiness checks rather than `??`: a blank value parses fine and would otherwise
    // reach the create form as an empty name.
    if (!name) {
        throw new Error(`Scout skill file ${source} is missing a name`)
    }
    if (!description) {
        throw new Error(`Scout skill file ${source} is missing a description`)
    }

    return {
        name,
        description,
        body: raw.slice(match[0].length).trim(),
        // `scout-tags` is the canonical frontmatter field for a scout's config tags, so the file
        // carries them too and stays liftable into products/signals/skills/ unchanged.
        config: { ...DAILY_AT_9AM, tags: frontmatter['scout-tags'] ?? [] },
    }
}

export const AI_OBSERVABILITY_SCOUT_TEMPLATES: AIObservabilityScoutTemplate[] = [
    {
        key: 'daily-digest',
        title: 'Daily digest',
        description: 'Summarize meaningful changes in AI usage, cost, errors, costly users, and evaluations.',
        schedule: 'Daily at 9:00 AM',
        initialValues: readScoutSkill(dailyDigestSkill, 'signals-scout-ai-observability-daily-digest.md'),
    },
    {
        key: 'costly-users',
        title: 'Costly or unusual users',
        description: 'Find unusual usage and very costly users, then trace the spend to a cause you can act on.',
        schedule: 'Daily at 9:00 AM',
        initialValues: readScoutSkill(costlyUsersSkill, 'signals-scout-ai-observability-costly-users.md'),
    },
    {
        key: 'error-patterns',
        title: 'Error patterns',
        description: 'Read real traces to find recurring errors and silent AI failures worth fixing.',
        schedule: 'Daily at 9:00 AM',
        initialValues: readScoutSkill(errorPatternsSkill, 'signals-scout-ai-observability-error-patterns.md'),
    },
]

/** Looks a template up by key. Returns undefined for anything not in the list, so an untrusted
 * value (a URL fragment, say) can be resolved and validated in one step. */
export function findAIObservabilityScoutTemplate(key: unknown): AIObservabilityScoutTemplate | undefined {
    return AI_OBSERVABILITY_SCOUT_TEMPLATES.find((template) => template.key === key)
}

export function isAIObservabilityScout(config: SignalScoutConfigApi): boolean {
    return scoutTags(config).includes(AI_OBSERVABILITY_SCOUT_TAG)
}
