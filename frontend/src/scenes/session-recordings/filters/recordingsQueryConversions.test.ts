import { RecordingsQuery } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    LogEntryPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
} from '~/types'

import {
    convertUniversalFiltersToRecordingsQuery,
    recordingsQueryToUniversalFilters,
} from './recordingsQueryConversions'

const EMPTY_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

function rq(partial: Partial<RecordingsQuery>): RecordingsQuery {
    return { kind: 'RecordingsQuery' as RecordingsQuery['kind'], ...partial }
}

function innerValues(query: RecordingsQuery | null | undefined): any[] {
    const inner = recordingsQueryToUniversalFilters(query).filter_group.values[0] as { values: any[] }
    return inner.values
}

const EVENT = { id: '$pageview', type: 'events' }
const ACTION = { id: '5', type: 'actions' }
const PERSON_PROP: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    value: 'a@b.com',
    operator: PropertyOperator.Exact,
}
const CONSOLE_LOG: LogEntryPropertyFilter = {
    type: PropertyFilterType.LogEntry,
    key: 'level',
    value: ['error'],
    operator: PropertyOperator.Exact,
}
const SNAPSHOT_SOURCE: AnyPropertyFilter = {
    type: PropertyFilterType.Recording,
    key: 'snapshot_source',
    value: ['web'],
    operator: PropertyOperator.Exact,
}
const COMMENT_TEXT: AnyPropertyFilter = {
    type: PropertyFilterType.Recording,
    key: 'comment_text',
    value: 'bug',
    operator: PropertyOperator.IContains,
}
const durationFilter = (key: 'duration' | 'active_seconds' | 'inactive_seconds'): AnyPropertyFilter => ({
    type: PropertyFilterType.Recording,
    key,
    value: 5,
    operator: PropertyOperator.GreaterThan,
})

describe('recordingsQueryToUniversalFilters', () => {
    describe('empty / nullish input', () => {
        it.each([
            ['null', null],
            ['undefined', undefined],
            ['empty query', rq({})],
            ['empty arrays', rq({ events: [], actions: [], properties: [], having_predicates: [] })],
        ])('%s yields an empty inner group, no duration, untoggled test accounts', (_name, input) => {
            const universal = recordingsQueryToUniversalFilters(input as RecordingsQuery | null)
            expect(universal.filter_group).toEqual(EMPTY_GROUP)
            expect(universal.duration).toEqual([])
            expect(universal.filter_test_accounts).toBe(false)
        })
    })

    describe('single-dimension pass-through', () => {
        it.each<[string, Partial<RecordingsQuery>, any[]]>([
            ['events', { events: [EVENT] }, [EVENT]],
            ['actions', { actions: [ACTION] }, [ACTION]],
            ['properties', { properties: [PERSON_PROP] }, [PERSON_PROP]],
            ['console_log_filters', { console_log_filters: [CONSOLE_LOG] }, [CONSOLE_LOG]],
            ['comment_text', { comment_text: COMMENT_TEXT }, [COMMENT_TEXT]],
        ])('passes %s through unchanged', (_name, partial, expected) => {
            expect(innerValues(rq(partial))).toEqual(expected)
        })

        it('hidden events filter (the classifier regression case)', () => {
            const events = [{ id: 'taxonomic filter add filter clicked', type: 'events' }]
            expect(innerValues(rq({ events }))).toEqual(events)
        })
    })

    describe('having_predicates routing', () => {
        it.each(['duration', 'active_seconds', 'inactive_seconds'] as const)(
            'routes the %s duration key into duration, not the group',
            (key) => {
                const universal = recordingsQueryToUniversalFilters(rq({ having_predicates: [durationFilter(key)] }))
                expect(universal.duration).toEqual([durationFilter(key)])
                expect(innerValues(rq({ having_predicates: [durationFilter(key)] }))).toEqual([])
            }
        )
        it('keeps non-duration recording properties (snapshot_source) in the group', () => {
            const universal = recordingsQueryToUniversalFilters(rq({ having_predicates: [SNAPSHOT_SOURCE] }))
            expect(universal.duration).toEqual([])
            expect(innerValues(rq({ having_predicates: [SNAPSHOT_SOURCE] }))).toEqual([SNAPSHOT_SOURCE])
        })
        it('splits a mixed list, preserving multiple durations and the rest in the group', () => {
            const query = rq({
                having_predicates: [durationFilter('active_seconds'), SNAPSHOT_SOURCE, durationFilter('duration')],
            })
            const universal = recordingsQueryToUniversalFilters(query)
            expect(universal.duration).toEqual([durationFilter('active_seconds'), durationFilter('duration')])
            expect(innerValues(query)).toEqual([SNAPSHOT_SOURCE])
        })
        it('keeps a non-recording having predicate in the group (defensive)', () => {
            const query = rq({ having_predicates: [PERSON_PROP] })
            expect(recordingsQueryToUniversalFilters(query).duration).toEqual([])
            expect(innerValues(query)).toEqual([PERSON_PROP])
        })
    })

    describe('filter_test_accounts', () => {
        it.each([
            [true, true],
            [false, false],
            [undefined, false],
        ])('maps %s to %s', (input, expected) => {
            expect(recordingsQueryToUniversalFilters(rq({ filter_test_accounts: input })).filter_test_accounts).toBe(
                expected
            )
        })
    })

    describe('multi-dimension ordering', () => {
        it('concatenates every dimension in a stable order: events, actions, properties, console, non-duration having, comment', () => {
            const query = rq({
                events: [EVENT],
                actions: [ACTION],
                properties: [PERSON_PROP],
                console_log_filters: [CONSOLE_LOG],
                having_predicates: [durationFilter('active_seconds'), SNAPSHOT_SOURCE],
                comment_text: COMMENT_TEXT,
                filter_test_accounts: true,
            })
            const universal = recordingsQueryToUniversalFilters(query)
            expect(universal.duration).toEqual([durationFilter('active_seconds')])
            expect(universal.filter_test_accounts).toBe(true)
            expect(innerValues(query)).toEqual([EVENT, ACTION, PERSON_PROP, CONSOLE_LOG, SNAPSHOT_SOURCE, COMMENT_TEXT])
        })

        it('preserves multiples within a single dimension', () => {
            const second = { id: '$autocapture', type: 'events' }
            expect(innerValues(rq({ events: [EVENT, second] }))).toEqual([EVENT, second])
        })
    })

    it('always wraps values in the outer/inner AND nesting UniversalFilters expects', () => {
        const universal = recordingsQueryToUniversalFilters(rq({ events: [EVENT] }))
        expect(universal.filter_group.type).toBe(FilterLogicalOperator.And)
        expect(universal.filter_group.values).toHaveLength(1)
        const inner = universal.filter_group.values[0] as { type: FilterLogicalOperator; values: any[] }
        expect(inner.type).toBe(FilterLogicalOperator.And)
    })
})

// Now that both directions live in this leaf module, the editor's load→edit→save loop is testable
// end to end: forward(reverse(query)) must preserve every filter dimension. The forward converter
// normalizes/re-routes some values, so these assert per-dimension equivalence rather than deep object equality.
describe('convertUniversalFiltersToRecordingsQuery ∘ recordingsQueryToUniversalFilters', () => {
    function roundTrip(query: RecordingsQuery): RecordingsQuery {
        return convertUniversalFiltersToRecordingsQuery(recordingsQueryToUniversalFilters(query))
    }

    it('preserves events, actions, and properties (value normalized to an array for multi-select operators)', () => {
        const query = rq({ events: [EVENT], actions: [ACTION], properties: [PERSON_PROP] })
        const back = roundTrip(query)
        expect(back.events).toEqual([EVENT])
        expect(back.actions).toEqual([ACTION])
        expect(back.properties).toHaveLength(1)
        // The forward converter coerces an Exact-operator value to an array; key/type/operator are unchanged.
        expect(back.properties![0]).toMatchObject({
            type: PERSON_PROP.type,
            key: PERSON_PROP.key,
            operator: PERSON_PROP.operator,
            value: [PERSON_PROP.value],
        })
    })

    it('preserves the classifier events filter that was previously hidden', () => {
        const events = [{ id: 'taxonomic filter add filter clicked', type: 'events' }]
        expect(roundTrip(rq({ events })).events).toEqual(events)
    })

    it('preserves a duration having-predicate', () => {
        const query = rq({ having_predicates: [durationFilter('active_seconds')] })
        expect(roundTrip(query).having_predicates).toContainEqual(durationFilter('active_seconds'))
    })

    it('preserves every duration having-predicate, not just the first', () => {
        const query = rq({ having_predicates: [durationFilter('active_seconds'), durationFilter('duration')] })
        const back = roundTrip(query).having_predicates
        expect(back).toContainEqual(durationFilter('active_seconds'))
        expect(back).toContainEqual(durationFilter('duration'))
    })

    it('preserves filter_test_accounts', () => {
        expect(roundTrip(rq({ filter_test_accounts: true })).filter_test_accounts).toBe(true)
    })

    it('preserves an OR operand instead of silently downgrading to AND', () => {
        expect(roundTrip(rq({ operand: FilterLogicalOperator.Or })).operand).toBe(FilterLogicalOperator.Or)
    })

    it('an empty query round-trips to an empty (match-all) query', () => {
        const back = roundTrip(rq({}))
        expect(back.events).toEqual([])
        expect(back.actions).toEqual([])
        expect(back.properties).toEqual([])
    })
})

describe('convertUniversalFiltersToRecordingsQuery operand derivation', () => {
    const VISITED_PAGE: AnyPropertyFilter = {
        type: PropertyFilterType.Recording,
        key: 'visited_page',
        value: '/cart',
        operator: PropertyOperator.IContains,
    }
    const uf = (outer: FilterLogicalOperator, inner: FilterLogicalOperator): RecordingUniversalFilters =>
        ({
            date_from: '-3d',
            date_to: null,
            duration: [],
            filter_test_accounts: false,
            filter_group: { type: outer, values: [{ type: inner, values: [VISITED_PAGE] }] },
        }) as RecordingUniversalFilters

    it.each([
        ['inner group only', FilterLogicalOperator.And, FilterLogicalOperator.Or, FilterLogicalOperator.Or],
        ['no group', FilterLogicalOperator.And, FilterLogicalOperator.And, FilterLogicalOperator.And],
        ['outer group only', FilterLogicalOperator.Or, FilterLogicalOperator.And, FilterLogicalOperator.Or],
    ])('match-any on %s yields operand %s/%s -> %s', (_name, outer, inner, expected) => {
        expect(convertUniversalFiltersToRecordingsQuery(uf(outer, inner)).operand).toBe(expected)
    })
})
