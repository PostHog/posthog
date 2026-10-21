import type { CohortUsedInResponseApi } from 'products/cohorts/frontend/generated/api.schemas'

import { cohortUsedInSections } from './cohortUsedIn'

const usedIn: CohortUsedInResponseApi = {
    feature_flags: {
        results: [
            { id: 1, key: 'live-flag', name: 'Live flag', active: true },
            { id: 2, key: 'paused-flag', name: 'Paused flag', active: false },
        ],
        total: 2,
        has_more: false,
    },
    insights: { results: [], total: 0, has_more: false },
    cohorts: { results: [], total: 0, has_more: false },
    test_account_filters: {
        results: [{ id: 42, name: 'Staging' }],
        total: 1,
        has_more: false,
    },
    workflows: { results: [], total: 0, hidden: 0, has_more: false },
}

describe('cohortUsedInSections', () => {
    it('reports every reference, and links each environment to its own settings', () => {
        const sections = cohortUsedInSections(usedIn)

        expect(sections.map(({ title, total }) => [title, total])).toEqual([
            ['Feature flags', 2],
            ['Filter out internal and test users', 1],
        ])
        expect(sections[1].items[0].url).toEqual(
            '/project/42/settings/environment-customization#internal-user-filtering'
        )
    })

    it('keeps only the references that block a delete', () => {
        const sections = cohortUsedInSections(usedIn, { blockingOnly: true })

        // A paused flag never blocks a delete, so listing it would send the user to fix nothing.
        expect(sections[0].items.map(({ label }) => label)).toEqual(['Live flag'])
        expect(sections[0].total).toEqual(1)
    })

    it.each([
        [
            'some of them are visible',
            { results: [{ id: 'wf-1', name: 'Onboarding', status: 'active' }], total: 3, hidden: 2, has_more: true },
            ['Onboarding'],
        ],
        ['none of them are visible', { results: [], total: 1, hidden: 1, has_more: true }, []],
    ])('lists relying workflows as delete blockers when %s', (_, workflows, labels) => {
        const withWorkflows: CohortUsedInResponseApi = { ...usedIn, workflows }
        const section = cohortUsedInSections(withWorkflows, { blockingOnly: true }).find(
            ({ title }) => title === 'Workflows'
        )

        expect(section).toMatchObject({ total: workflows.total, hidden: workflows.hidden })
        expect(section?.items.map(({ label }) => label)).toEqual(labels)
        expect(cohortUsedInSections(withWorkflows).map(({ title }) => title)).not.toContain('Workflows')
    })

    it('returns nothing for a cohort no-one references', () => {
        const empty = { results: [], total: 0, has_more: false }

        expect(
            cohortUsedInSections({
                feature_flags: empty,
                insights: empty,
                cohorts: empty,
                test_account_filters: empty,
                workflows: { ...empty, hidden: 0 },
            })
        ).toEqual([])
    })
})
