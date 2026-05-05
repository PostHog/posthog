import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope, FilterLogicalOperator } from '~/types'

import { cohortActivityDescriber } from './activityDescriptions'

function makeLogItem(overrides: Partial<ActivityLogItem> & { detail: ActivityLogItem['detail'] }): ActivityLogItem {
    return {
        user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
        activity: 'updated',
        created_at: '2026-03-01T00:00:00Z',
        scope: ActivityScope.COHORT,
        item_id: '7',
        ...overrides,
    }
}

function describeText(logItem: ActivityLogItem): string {
    const { description } = cohortActivityDescriber(logItem)
    if (!description) {
        return ''
    }
    const { container } = render(<>{description}</>)
    return container.textContent ?? ''
}

const change = (field: string, before: unknown, after: unknown): ActivityChange => ({
    type: ActivityScope.COHORT,
    action: 'changed',
    field,
    before: before as ActivityChange['before'],
    after: after as ActivityChange['after'],
})

const filtersWith = (numCriteria: number): { properties: { type: FilterLogicalOperator; values: any[] } } => ({
    properties: {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: Array.from({ length: numCriteria }, (_, i) => ({ key: `prop_${i}` })),
            },
        ],
    },
})

describe('cohortActivityDescriber', () => {
    beforeEach(() => {
        // describer returns JSX containing <Link> which relies on kea-router
        initKeaTests()
    })

    it('returns null for non-cohort scope', () => {
        const result = cohortActivityDescriber({
            ...makeLogItem({ detail: { name: 'x', merge: null, trigger: null, changes: [] } }),
            scope: ActivityScope.FEATURE_FLAG,
        })
        expect(result.description).toBeNull()
    })

    it('describes creation', () => {
        expect(
            describeText(
                makeLogItem({
                    activity: 'created',
                    detail: { name: 'High value users', merge: null, trigger: null, changes: [] },
                })
            )
        ).toBe('Max Hog created the cohort: High value users')
    })

    it('describes deletion', () => {
        expect(
            describeText(
                makeLogItem({
                    activity: 'deleted',
                    detail: { name: 'High value users', merge: null, trigger: null, changes: [] },
                })
            )
        ).toBe('Max Hog deleted the cohort: High value users')
    })

    it('describes restoration', () => {
        expect(
            describeText(
                makeLogItem({
                    activity: 'restored',
                    detail: { name: 'High value users', merge: null, trigger: null, changes: [] },
                })
            )
        ).toBe('Max Hog restored the cohort: High value users')
    })

    it('describes manual person additions', () => {
        expect(
            describeText(
                makeLogItem({
                    activity: 'persons_added_manually',
                    detail: { name: 'Beta testers', merge: null, trigger: null, changes: [] },
                })
            )
        ).toBe('Max Hog added users to the cohort: Beta testers')
    })

    it('describes manual person removals', () => {
        expect(
            describeText(
                makeLogItem({
                    activity: 'person_removed_manually',
                    detail: { name: 'Beta testers', merge: null, trigger: null, changes: [] },
                })
            )
        ).toBe('Max Hog removed a user from the cohort: Beta testers')
    })

    describe('updated activity', () => {
        it('describes a rename', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: 'New name',
                        merge: null,
                        trigger: null,
                        changes: [change('name', 'Old name', 'New name')],
                    },
                })
            )
            expect(text).toContain('renamed from Old name to New name')
            expect(text).toContain('on New name')
        })

        it('describes adding a description', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('description', null, 'Some description')],
                        },
                    })
                )
            ).toContain('added a description')
        })

        it('describes clearing a description', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('description', 'Some description', '')],
                        },
                    })
                )
            ).toContain('cleared the description')
        })

        it('describes editing an existing description', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('description', 'Old text', 'New text')],
                        },
                    })
                )
            ).toContain('updated the description')
        })

        it('describes a criteria count change', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('filters', filtersWith(2), filtersWith(5))],
                        },
                    })
                )
            ).toContain('changed the matching criteria from 2 to 5')
        })

        it('describes a criteria edit when count is unchanged', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('filters', filtersWith(3), filtersWith(3))],
                        },
                    })
                )
            ).toContain('updated the matching criteria')
        })

        it('describes a query change', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('query', { kind: 'a' }, { kind: 'b' })],
                        },
                    })
                )
            ).toContain('updated the cohort query')
        })

        it('dedupes is_static when cohort_type is also present', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: 'My cohort',
                        merge: null,
                        trigger: null,
                        changes: [change('is_static', false, true), change('cohort_type', 'person', 'static')],
                    },
                })
            )
            const occurrences = text.match(/changed the cohort type/g) ?? []
            expect(occurrences).toHaveLength(1)
            expect(text).toContain('changed the cohort type to static')
        })

        it('describes is_static alone when cohort_type is not present', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: {
                            name: 'My cohort',
                            merge: null,
                            trigger: null,
                            changes: [change('is_static', false, true)],
                        },
                    })
                )
            ).toContain('changed the cohort type to static')
        })

        it('surfaces unknown fields generically rather than dumping JSON', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: 'My cohort',
                        merge: null,
                        trigger: null,
                        changes: [change('newly_added_field', 'a', 'b')],
                    },
                })
            )
            expect(text).toContain('updated newly_added_field')
            expect(text).not.toContain('"a"')
        })

        it('combines multiple known field changes', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: 'New name',
                        merge: null,
                        trigger: null,
                        changes: [
                            change('name', 'Old', 'New name'),
                            change('description', null, 'Some description'),
                            change('filters', filtersWith(1), filtersWith(2)),
                        ],
                    },
                })
            )
            expect(text).toContain('renamed from Old to New name')
            expect(text).toContain('added a description')
            expect(text).toContain('changed the matching criteria from 1 to 2')
        })

        it('falls back to a generic line when changes array is empty', () => {
            expect(
                describeText(
                    makeLogItem({
                        detail: { name: 'My cohort', merge: null, trigger: null, changes: [] },
                    })
                )
            ).toBe('Max Hog updated the cohort: My cohort')
        })

        it('skips excluded fields without rendering them', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: 'My cohort',
                        merge: null,
                        trigger: null,
                        changes: [change('id', 1, 2), change('team_id', 1, 2), change('created_at', 'a', 'b')],
                    },
                })
            )
            // all three are excluded -> falls back to the generic "updated" line
            expect(text).toBe('Max Hog updated the cohort: My cohort')
        })
    })
})
