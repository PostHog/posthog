import { render } from '@testing-library/react'

import { ActivityLogItem, HumanizedChange } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { experimentActivityDescriber } from './experimentActivityDescriber'

const textOf = (result: HumanizedChange): string => {
    const { container } = render(<>{result.description}</>)
    return container.textContent ?? ''
}

const baseLogItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-05-21T00:00:00Z',
    scope: 'Experiment',
    item_id: '42',
    user: { first_name: 'Alice', last_name: 'Adams', email: 'alice@example.com' },
    detail: { name: 'Checkout funnel', changes: null, merge: null, trigger: null },
    ...overrides,
})

describe('experimentActivityDescriber', () => {
    describe('saved_metric_config rows', () => {
        it.each([
            {
                name: 'created: "added shared metric X to experiment"',
                activity: 'created',
                expected: ['Alice Adams', 'added shared metric', 'Conversion rate', 'experiment'],
                notExpected: ['created a new', 'deleted'],
            },
            {
                name: 'updated: "updated configuration for shared metric X on experiment"',
                activity: 'updated',
                expected: ['Alice Adams', 'updated configuration for shared metric', 'Conversion rate', 'experiment'],
                notExpected: ['created a new', 'deleted'],
            },
            {
                name: 'deleted: "removed shared metric X from experiment"',
                activity: 'deleted',
                expected: ['Alice Adams', 'removed shared metric', 'Conversion rate', 'experiment'],
                notExpected: ['deleted experiment:', 'created a new'],
            },
        ])('$name', ({ activity, expected, notExpected }) => {
            const result = experimentActivityDescriber(
                baseLogItem({
                    activity,
                    detail: {
                        name: 'Conversion rate',
                        type: 'saved_metric_config',
                        changes: [],
                        merge: null,
                        trigger: null,
                    },
                })
            )
            const text = textOf(result)
            for (const fragment of expected) {
                expect(text).toContain(fragment)
            }
            for (const fragment of notExpected) {
                expect(text).not.toContain(fragment)
            }
        })
    })

    describe('metric reorder rows on the experiment scope', () => {
        it.each([
            {
                name: 'primary reorder',
                field: 'primary_metrics_ordered_uuids',
                expectedFragment: 'reordered the primary metrics',
            },
            {
                name: 'secondary reorder',
                field: 'secondary_metrics_ordered_uuids',
                expectedFragment: 'reordered the secondary metrics',
            },
        ])('$name: "$expectedFragment for Checkout funnel"', ({ field, expectedFragment }) => {
            const result = experimentActivityDescriber(
                baseLogItem({
                    activity: 'updated',
                    detail: {
                        name: 'Checkout funnel',
                        changes: [
                            {
                                type: ActivityScope.EXPERIMENT,
                                action: 'changed',
                                field,
                                before: ['uuid-a', 'uuid-b'],
                                after: ['uuid-b', 'uuid-a'],
                            },
                        ],
                        merge: null,
                        trigger: null,
                    },
                })
            )
            const text = textOf(result)
            expect(text).toContain('Alice Adams')
            expect(text).toContain(expectedFragment)
            expect(text).toContain('Checkout funnel')
            // The reorder must not bleed into the saved_metric_config copy
            expect(text).not.toContain('shared metric')
        })

        it('does not describe a reorder when the same UUIDs are passed as before/after', () => {
            const result = experimentActivityDescriber(
                baseLogItem({
                    activity: 'updated',
                    detail: {
                        name: 'Checkout funnel',
                        changes: [
                            {
                                type: ActivityScope.EXPERIMENT,
                                action: 'changed',
                                field: 'primary_metrics_ordered_uuids',
                                before: ['uuid-a', 'uuid-b'],
                                after: ['uuid-a', 'uuid-b'],
                            },
                        ],
                        merge: null,
                        trigger: null,
                    },
                })
            )
            expect(textOf(result)).not.toContain('reordered')
        })
    })
})
