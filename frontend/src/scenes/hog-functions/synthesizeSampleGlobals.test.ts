import {
    CyclotronJobFiltersType,
    CyclotronJobInputType,
    CyclotronJobInvocationGlobals,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { collectReferencedPaths, synthesizeSampleGlobals } from './synthesizeSampleGlobals'

const baseGlobals = (): CyclotronJobInvocationGlobals => ({
    project: { id: 1, name: 'Test', url: 'https://app.example/project/1' },
    event: {
        uuid: 'event-uuid',
        event: '$pageview',
        distinct_id: 'd1',
        elements_chain: '',
        properties: { existing: 'kept' },
        timestamp: '2026-01-01T00:00:00.000Z',
        url: 'https://app.example/project/1/events/event-uuid',
    },
    person: {
        id: 'p1',
        properties: {},
        name: 'Example person',
        url: 'https://app.example/person/p1',
    },
    groups: {},
})

describe('synthesizeSampleGlobals', () => {
    it('overrides the event name from the first configured event filter', () => {
        const filters: CyclotronJobFiltersType = { events: [{ id: 'signup', name: 'signup', type: 'events' }] }
        const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
        expect(result.event.event).toBe('signup')
    })

    it('falls back to the base event name when no event id is configured', () => {
        const result = synthesizeSampleGlobals({
            base: baseGlobals(),
            filters: { events: [] },
            inputs: null,
        })
        expect(result.event.event).toBe('$pageview')
    })

    it('preserves existing event properties on the base globals', () => {
        const result = synthesizeSampleGlobals({ base: baseGlobals(), filters: null, inputs: null })
        expect(result.event.properties.existing).toBe('kept')
    })

    it('does not mutate the base globals object', () => {
        const base = baseGlobals()
        synthesizeSampleGlobals({
            base,
            filters: {
                properties: [
                    { type: PropertyFilterType.Event, key: 'k', value: 'v', operator: PropertyOperator.Exact },
                ],
            },
            inputs: null,
        })
        expect(base.event.properties).toEqual({ existing: 'kept' })
    })

    describe('property filter satisfaction', () => {
        const cases: Array<{
            name: string
            operator: PropertyOperator
            value: unknown
            expected: unknown
        }> = [
            { name: 'exact takes the value', operator: PropertyOperator.Exact, value: 'us', expected: 'us' },
            {
                name: 'exact takes the first array element',
                operator: PropertyOperator.Exact,
                value: ['us', 'gb'],
                expected: 'us',
            },
            {
                name: 'is_set assigns a placeholder',
                operator: PropertyOperator.IsSet,
                value: undefined,
                expected: 'example',
            },
            {
                name: 'icontains assigns the substring',
                operator: PropertyOperator.IContains,
                value: 'test',
                expected: 'test',
            },
            { name: 'in takes the first array entry', operator: PropertyOperator.In, value: ['a', 'b'], expected: 'a' },
            { name: 'gt produces value + 1', operator: PropertyOperator.GreaterThan, value: 10, expected: 11 },
            { name: 'lt produces value - 1', operator: PropertyOperator.LessThan, value: 10, expected: 9 },
            {
                name: 'between produces the midpoint',
                operator: PropertyOperator.Between,
                value: [10, 20],
                expected: 15,
            },
            {
                name: 'is_not assigns a value distinct from the disallowed one',
                operator: PropertyOperator.IsNot,
                value: 'banned',
                expected: 'not-banned',
            },
        ]

        for (const { name, operator, value, expected } of cases) {
            it(name, () => {
                const filters: CyclotronJobFiltersType = {
                    properties: [{ type: PropertyFilterType.Event, key: 'country', value, operator } as any],
                }
                const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
                expect(result.event.properties.country).toEqual(expected)
            })
        }

        it('is_not_set leaves the key absent', () => {
            const filters: CyclotronJobFiltersType = {
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: 'should_not_exist',
                        value: undefined,
                        operator: PropertyOperator.IsNotSet,
                    } as any,
                ],
            }
            const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
            expect('should_not_exist' in result.event.properties).toBe(false)
        })

        it('routes person filters to person.properties', () => {
            const filters: CyclotronJobFiltersType = {
                properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: 'email',
                        value: 'a@b.com',
                        operator: PropertyOperator.Exact,
                    } as any,
                ],
            }
            const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
            expect(result.person?.properties.email).toBe('a@b.com')
            expect('email' in result.event.properties).toBe(false)
        })

        it('ignores HogQL filters (cannot synthesize from arbitrary expressions)', () => {
            const filters: CyclotronJobFiltersType = {
                properties: [{ type: PropertyFilterType.HogQL, key: "event = '$pageview'" } as any],
            }
            const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
            expect(Object.keys(result.event.properties)).toEqual(['existing'])
        })

        it('applies event-level property filters', () => {
            const filters: CyclotronJobFiltersType = {
                events: [
                    {
                        id: 'signup',
                        name: 'signup',
                        type: 'events',
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: 'plan',
                                value: 'pro',
                                operator: PropertyOperator.Exact,
                            } as any,
                        ],
                    },
                ],
            }
            const result = synthesizeSampleGlobals({ base: baseGlobals(), filters, inputs: null })
            expect(result.event.properties.plan).toBe('pro')
        })
    })

    describe('input template references', () => {
        const inputs = (value: any): Record<string, CyclotronJobInputType> => ({ slack_message: { value } })

        it('fills event.properties paths referenced from string templates', () => {
            const result = synthesizeSampleGlobals({
                base: baseGlobals(),
                filters: null,
                inputs: inputs('Hello {event.properties.company}, your plan is {event.properties.plan}'),
            })
            expect(result.event.properties.company).toBe('example')
            expect(result.event.properties.plan).toBe('example')
        })

        it('fills person.properties paths', () => {
            const result = synthesizeSampleGlobals({
                base: baseGlobals(),
                filters: null,
                inputs: inputs('{person.properties.email}'),
            })
            expect(result.person?.properties.email).toBe('example')
        })

        it('does not overwrite an existing filter-derived value', () => {
            const result = synthesizeSampleGlobals({
                base: baseGlobals(),
                filters: {
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: 'plan',
                            value: 'pro',
                            operator: PropertyOperator.Exact,
                        } as any,
                    ],
                },
                inputs: inputs('{event.properties.plan}'),
            })
            expect(result.event.properties.plan).toBe('pro')
        })

        it('walks nested object/array input values', () => {
            const result = synthesizeSampleGlobals({
                base: baseGlobals(),
                filters: null,
                inputs: inputs({ blocks: [{ text: '{event.properties.deeply_nested}' }] }),
            })
            expect(result.event.properties.deeply_nested).toBe('example')
        })

        it('ignores references whose root is not event/person/groups', () => {
            const result = synthesizeSampleGlobals({
                base: baseGlobals(),
                filters: null,
                inputs: inputs('{inputs.foo} {project.id} {source.name}'),
            })
            expect(result.event.properties).toEqual({ existing: 'kept' })
        })
    })

    describe('collectReferencedPaths', () => {
        it('returns the unique set of dotted paths across all inputs', () => {
            const paths = collectReferencedPaths({
                a: { value: '{event.properties.x} {person.properties.y}' },
                b: { value: '{event.properties.x}' }, // duplicate
                c: { value: 42 }, // non-string ignored
            })
            expect(paths.sort()).toEqual(['event.properties.x', 'person.properties.y'])
        })
    })
})
