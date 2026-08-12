import { getAIObservabilityDigestScoutInitialValues } from './AIObservabilityDigestScoutButton'

describe('AI observability daily digest scout template', () => {
    it('prefills a daily 9 a.m. scout that reviews canonical AI observability data and always produces one digest', () => {
        const initialValues = getAIObservabilityDigestScoutInitialValues()

        expect(initialValues).toMatchObject({
            name: 'signals-scout-ai-observability-daily-digest',
            config: {
                enabled: true,
                emit: true,
                run_interval_minutes: 1440,
                run_cron_schedule: '0 9 * * *',
                tags: ['ai-observability'],
            },
        })
        expect(initialValues.body).toEqual(expect.stringContaining('/project/{team_id}/ai-observability/dashboard'))
        expect(initialValues.body).toEqual(expect.stringContaining('must not be used for this surface'))
        expect(initialValues.body).toEqual(expect.stringContaining('preinstalled in the Scout runtime'))
        for (const skillName of [
            'exploring-ai-failures',
            'exploring-llm-traces',
            'analyzing-expensive-users',
            'exploring-llm-costs',
            'exploring-llm-evaluations',
            'querying-posthog-data',
        ]) {
            expect(initialValues.body).toEqual(expect.stringContaining(`\`${skillName}\``))
        }
        expect(initialValues.body).toEqual(
            expect.stringContaining('`skill-get` is only for loading this bound Scout skill')
        )
        expect(initialValues.body).toEqual(
            expect.stringContaining("both this Scout's exact `skill_name` and its current `skill_version`")
        )
        expect(initialValues.body).toEqual(
            expect.stringContaining('whose `created_by_skill` exactly matches this Scout')
        )
        expect(initialValues.body).toEqual(expect.stringContaining('Do not repeat an unchanged issue'))
        expect(initialValues.body).toEqual(
            expect.stringContaining('Every successful run must leave exactly one report')
        )
        expect(initialValues.body).toEqual(expect.stringContaining('No material regressions'))
        expect(initialValues.body).toEqual(expect.stringContaining('list any incomplete surface'))
        expect(initialValues.body).toEqual(
            expect.stringContaining('Every included item must lead to a concrete next action')
        )
    })
})
