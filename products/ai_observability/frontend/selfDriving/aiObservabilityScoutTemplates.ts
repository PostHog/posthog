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

/**
 * Splits a scout's `SKILL.md` into the three fields the create form takes separately. The file is
 * the single source for the scout itself — posthog.com's pocket guides fetch the same one — so
 * everything here is read from it rather than restated.
 */
function readScoutSkill(raw: string): Pick<ScoutCreateInitialValues, 'name' | 'description' | 'body'> {
    const match = raw.match(FRONTMATTER_BLOCK)
    if (!match) {
        throw new Error('Scout skill file is missing its frontmatter')
    }
    const { name, description } = parseYaml(match[1]) as { name?: string; description?: string }
    if (!name || !description) {
        throw new Error(`Scout skill file ${name ?? '(unnamed)'} is missing name or description`)
    }
    return { name, description: description.trim(), body: raw.slice(match[0].length).trim() }
}

/** Every template runs daily at 9 a.m. and writes to the inbox under the AI observability tag. */
const DAILY_AT_9AM: ScoutCreateInitialValues['config'] = {
    enabled: true,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: '0 9 * * *',
    tags: [AI_OBSERVABILITY_SCOUT_TAG],
}

export const AI_OBSERVABILITY_SCOUT_TEMPLATES: AIObservabilityScoutTemplate[] = [
    {
        key: 'daily-digest',
        title: 'Daily digest',
        description: 'Summarize meaningful changes in AI usage, cost, errors, costly users, and evaluations.',
        schedule: 'Daily at 9:00 AM',
        initialValues: { ...readScoutSkill(dailyDigestSkill), config: DAILY_AT_9AM },
    },
    {
        key: 'costly-users',
        title: 'Costly or unusual users',
        description: 'Find unusual usage and very costly users, then trace the spend to a cause you can act on.',
        schedule: 'Daily at 9:00 AM',
        initialValues: { ...readScoutSkill(costlyUsersSkill), config: DAILY_AT_9AM },
    },
    {
        key: 'error-patterns',
        title: 'Error patterns',
        description: 'Read real traces to find recurring errors and silent AI failures worth fixing.',
        schedule: 'Daily at 9:00 AM',
        initialValues: { ...readScoutSkill(errorPatternsSkill), config: DAILY_AT_9AM },
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
