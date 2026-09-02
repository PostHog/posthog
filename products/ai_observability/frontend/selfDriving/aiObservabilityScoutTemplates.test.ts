import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import {
    AI_OBSERVABILITY_SCOUT_TAG,
    AI_OBSERVABILITY_SCOUT_TEMPLATES,
    isAIObservabilityScout,
} from './aiObservabilityScoutTemplates'

describe('AI observability scout templates', () => {
    it('provides three uniquely named templates', () => {
        expect(AI_OBSERVABILITY_SCOUT_TEMPLATES).toHaveLength(3)

        const names = AI_OBSERVABILITY_SCOUT_TEMPLATES.map((template) => template.initialValues.name)
        expect(new Set(names).size).toBe(names.length)
    })

    it.each(AI_OBSERVABILITY_SCOUT_TEMPLATES)(
        '$title creates an enabled 9 a.m. daily scout with the product tag',
        ({ initialValues, schedule }) => {
            // Every field comes out of a SKILL.md parsed at module scope, so a malformed file is a
            // commit away. These assertions are what stops one reaching the eager import in
            // AIObservabilityScene.
            expect(initialValues.name).toMatch(/^signals-scout-ai-observability-/)
            expect(initialValues.description?.trim()).toBeTruthy()
            // The body is read out of a SKILL.md whose frontmatter carries name and description as
            // separate form fields. A broken strip would push `---\nname: ...` into Instructions.
            expect(initialValues.body).not.toMatch(/^---/)
            expect(initialValues.body).toMatch(/^# /)
            expect(schedule).toBe('Daily at 9:00 AM')
            expect(initialValues.config).toMatchObject({
                enabled: true,
                emit: true,
                run_interval_minutes: 1440,
                run_cron_schedule: '0 9 * * *',
                tags: [AI_OBSERVABILITY_SCOUT_TAG],
            })
        }
    )

    it.each([
        {
            name: 'tagged scout',
            config: { skill_name: 'signals-scout-custom', tags: [AI_OBSERVABILITY_SCOUT_TAG] },
            expected: true,
        },
        {
            name: 'legacy digest without a tag',
            config: { skill_name: 'signals-scout-ai-observability-daily-digest', tags: [] },
            expected: false,
        },
        {
            name: 'unrelated scout',
            config: { skill_name: 'signals-scout-unrelated', tags: ['other'] },
            expected: false,
        },
    ])('includes $name=$expected', ({ config, expected }) => {
        expect(isAIObservabilityScout(config as SignalScoutConfigApi)).toBe(expected)
    })
})
