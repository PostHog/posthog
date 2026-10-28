import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey, CohortClientErrors } from 'scenes/cohorts/CohortFilters/types'
import {
    cleanBehavioralTypeCriteria,
    cleanCriteria,
    cohortBroadcastDisabledReason,
    createCohortFormData,
    criteriaToHumanSentence,
    determineFilterType,
    isRecentPersonFilterUnsupported,
    validateGroup,
} from 'scenes/cohorts/cohortUtils'

import {
    AnyCohortCriteriaType,
    AnyPropertyFilter,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
    FilterLogicalOperator,
    PropertyDefinition,
    PropertyDefinitionState,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

describe('validateGroup', () => {
    function groupWithNegatedCriteria(criteria: AnyCohortCriteriaType[]): CohortCriteriaGroupFilter {
        // OR group + any negated criterion triggers the "negation requires AND" error path,
        // which is the branch that builds the human-readable error from BEHAVIORAL_TYPE_TO_LABEL.
        return {
            type: FilterLogicalOperator.Or,
            values: criteria,
        }
    }

    it.each<[PropertyOperator, string | string[], boolean]>([
        [PropertyOperator.SemverGte, '1.2.3', true],
        [PropertyOperator.SemverEq, '1.2.3-beta.1', true],
        [PropertyOperator.SemverEq, '1.2.3+build.42', true],
        [PropertyOperator.SemverEq, 'v1.2.3', true],
        [PropertyOperator.SemverEq, ['1.2.3'], true],
        [PropertyOperator.SemverGte, '01.2.3', false],
        [PropertyOperator.SemverGte, '2.0', false],
        [PropertyOperator.SemverLt, 'latest', false],
        [PropertyOperator.SemverTilde, '1.2', true],
        [PropertyOperator.SemverCaret, 'latest', false],
        [PropertyOperator.SemverWildcard, '1.2.*', true],
        [PropertyOperator.SemverWildcard, 'beta.*', false],
    ])('a %s criterion with value %s is valid: %s', (operator, value, isValid) => {
        const errors = validateGroup({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: BehavioralFilterKey.Person,
                    value: BehavioralEventType.HaveProperty,
                    key: '$app_version',
                    operator,
                    value_property: value,
                },
            ],
        })

        const criterionErrors = errors.values?.[0] as { value_property?: string } | undefined
        expect(criterionErrors?.value_property).toBe(isValid ? undefined : CohortClientErrors.InvalidSemverValue)
    })

    it('falls back to the raw filter type when the label map has no matching entry', () => {
        const group = groupWithNegatedCriteria([
            {
                type: BehavioralFilterKey.Behavioral,
                // A legacy/unknown value not present in BEHAVIORAL_TYPE_TO_LABEL.
                value: 'legacy_unknown_type' as BehavioralEventType,
                negation: true,
            },
        ])

        const errors = validateGroup(group)

        expect(typeof errors.id).toBe('string')
        expect(errors.id).toContain("'legacy_unknown_type'")
        expect(errors.id).not.toContain('undefined')
    })

    it('uses the mapped label for a known behavioral filter type', () => {
        const group = groupWithNegatedCriteria([
            {
                type: BehavioralFilterKey.Behavioral,
                // Negated PerformEvent resolves to NotPerformedEvent ("Did not complete event").
                value: BehavioralEventType.PerformEvent,
                negation: true,
            },
        ])

        const errors = validateGroup(group)

        expect(errors.id).toContain("'Did not complete event'")
    })

    it('does not crash when an AND group has one negated unknown-type criterion and one positive criterion', () => {
        // AND group with partial negation reaches the cancel-out check, which calls cleanCriteria on each
        // criterion. Before the fix, ROWS[unknownType] was undefined and destructuring it threw.
        const group: CohortCriteriaGroupFilter = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: BehavioralFilterKey.Behavioral,
                    value: 'legacy_unknown_type' as BehavioralEventType,
                    negation: true,
                },
                {
                    type: BehavioralFilterKey.Behavioral,
                    value: BehavioralEventType.PerformEvent,
                    negation: false,
                },
            ],
        }

        expect(() => validateGroup(group)).not.toThrow()
    })

    it('joins multiple negated criteria with a pluralized message', () => {
        const group = groupWithNegatedCriteria([
            {
                type: BehavioralFilterKey.Behavioral,
                value: 'legacy_unknown_type' as BehavioralEventType,
                negation: true,
            },
            {
                type: BehavioralFilterKey.Behavioral,
                value: BehavioralEventType.PerformEvent,
                negation: true,
            },
        ])

        const errors = validateGroup(group)

        // Exercises the `.join(', ')` and the `are` (vs `is a`) pluralization in the changed expression.
        expect(errors.id).toContain("'legacy_unknown_type', 'Did not complete event' are negative cohort criteria")
    })

    const negationGroup: CohortCriteriaGroupFilter = {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: BehavioralFilterKey.Behavioral,
                value: BehavioralEventType.PerformEvent,
                negation: true,
            },
        ],
    }
    const positiveSiblingGroup: CohortCriteriaGroupFilter = {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: BehavioralFilterKey.Behavioral,
                value: BehavioralEventType.PerformEvent,
                negation: false,
            },
        ],
    }

    it('allows a negation alone in its group when a sibling group has a positive criterion and outer op is AND', () => {
        // The reported bug: a "Did not complete event" negation in its own group, matched against a
        // positive criterion in a sibling group under the top-level "Match all criteria" (AND) operator.
        const errors = validateGroup(negationGroup, FilterLogicalOperator.And, [positiveSiblingGroup])

        expect(errors.id).toBeUndefined()
    })

    it('still rejects a negation alone in its group when the outer operator is OR', () => {
        // Under OR the sibling group is unioned, not intersected, so it cannot bound the negation.
        const errors = validateGroup(negationGroup, FilterLogicalOperator.Or, [positiveSiblingGroup])

        expect(errors.id).toContain(CohortClientErrors.NegationCriteriaMissingOther)
    })

    it('still rejects a negation alone in its group when no sibling group has a positive criterion', () => {
        const errors = validateGroup(negationGroup, FilterLogicalOperator.And, [negationGroup])

        expect(errors.id).toContain(CohortClientErrors.NegationCriteriaMissingOther)
    })

    it('still rejects a negation inside an inner OR group even when the outer operator is AND', () => {
        // A negation only makes sense intersected with a positive set. An OR group unions the negation
        // with its own members, so a positive sibling under outer AND must not rescue it.
        const orGroupWithNegation: CohortCriteriaGroupFilter = {
            type: FilterLogicalOperator.Or,
            values: [
                { type: BehavioralFilterKey.Behavioral, value: BehavioralEventType.PerformEvent, negation: true },
                { type: BehavioralFilterKey.Behavioral, value: BehavioralEventType.PerformEvent, negation: false },
            ],
        }
        const errors = validateGroup(orGroupWithNegation, FilterLogicalOperator.And, [positiveSiblingGroup])

        expect(errors.id).toContain(CohortClientErrors.NegationCriteriaMissingOther)
    })
})

describe('determineFilterType', () => {
    it('preserves PersonMetadata across the negation flow', () => {
        const negated = determineFilterType(BehavioralFilterKey.PersonMetadata, BehavioralEventType.HaveProperty, true)
        expect(negated.type).toBe(BehavioralFilterKey.PersonMetadata)
    })

    it('still maps regular Person criteria to Person on negation', () => {
        const negated = determineFilterType(BehavioralFilterKey.Person, BehavioralEventType.HaveProperty, true)
        expect(negated.type).toBe(BehavioralFilterKey.Person)
    })
})

describe('cleanBehavioralTypeCriteria', () => {
    // event_type is the transient taxonomic-group hint set when the user first picks a
    // property. It is dropped by later cleanCriteria passes, so the durable `type` must
    // survive on its own once derived.
    it('derives PersonMetadata type from the event_type hint on first selection', () => {
        const criteria: AnyCohortCriteriaType = {
            type: BehavioralFilterKey.Person,
            value: BehavioralEventType.HaveProperty,
            event_type: TaxonomicFilterGroupType.PersonMetadata,
        }
        expect(cleanBehavioralTypeCriteria(criteria).type).toBe(BehavioralFilterKey.PersonMetadata)
    })

    it('does not downgrade a loaded PersonMetadata criterion when event_type is gone', () => {
        const criteria: AnyCohortCriteriaType = {
            type: BehavioralFilterKey.PersonMetadata,
            value: BehavioralEventType.HaveProperty,
            // no event_type — mirrors a cohort loaded from the API
        }
        expect(cleanBehavioralTypeCriteria(criteria).type).toBe(BehavioralFilterKey.PersonMetadata)
    })

    it('maps a plain person property criterion to Person', () => {
        const criteria: AnyCohortCriteriaType = {
            type: BehavioralFilterKey.Person,
            value: BehavioralEventType.HaveProperty,
        }
        expect(cleanBehavioralTypeCriteria(criteria).type).toBe(BehavioralFilterKey.Person)
    })

    it('downgrades a PersonMetadata criterion to Person when the user switches to a plain person property', () => {
        // The picker merges the new selection's event_type onto the old criteria, so a
        // stale PersonMetadata `type` arrives alongside `event_type: PersonProperties`. The
        // fresh event_type must win, otherwise the criterion saves as `person_metadata` with
        // a non-metadata key and the server rejects the whole cohort.
        const criteria: AnyCohortCriteriaType = {
            type: BehavioralFilterKey.PersonMetadata,
            value: BehavioralEventType.HaveProperty,
            event_type: TaxonomicFilterGroupType.PersonProperties,
        }
        expect(cleanBehavioralTypeCriteria(criteria).type).toBe(BehavioralFilterKey.Person)
    })
})

describe('criteria whose value collides with an Object.prototype key', () => {
    // The API stores `value` as an unconstrained string, so keys like `constructor` can reach the
    // client. A plain ROWS lookup resolves those to a truthy non-row, which slips past both
    // functions' missing-row guards and then throws on the `fields` access behind them.
    const criteria = (value: string): AnyCohortCriteriaType => ({
        type: BehavioralFilterKey.Behavioral,
        value: value as BehavioralEventType,
        key: '$pageview',
    })

    it.each([['constructor'], ['toString'], ['__proto__']])('cleanCriteria empties the criterion for %s', (value) => {
        expect(cleanCriteria(criteria(value))).toEqual({ type: undefined, value: undefined, negation: false })
    })

    it.each([['constructor'], ['toString'], ['__proto__']])(
        'criteriaToHumanSentence renders nothing for %s',
        (value) => {
            expect(criteriaToHumanSentence(criteria(value), {}, {})).toEqual(<></>)
        }
    )
})

describe('cohortBroadcastDisabledReason', () => {
    const behavioral = { type: BehavioralFilterKey.Behavioral, value: BehavioralEventType.PerformEvent }
    const person = { type: BehavioralFilterKey.Person, key: 'email', value: 'is_set' }
    const cohort = (criteria: AnyCohortCriteriaType[], overrides: Partial<CohortType> = {}): CohortType => ({
        id: 1,
        groups: [],
        filters: {
            properties: {
                type: FilterLogicalOperator.Or,
                values: [{ type: FilterLogicalOperator.And, values: criteria }],
            },
        },
        ...overrides,
    })

    it.each([
        ['a property-based cohort', cohort([person as AnyCohortCriteriaType]), null],
        ['a static cohort built from events', cohort([behavioral as AnyCohortCriteriaType], { is_static: true }), null],
        [
            'an event condition in a nested group',
            cohort([person, behavioral] as AnyCohortCriteriaType[]),
            "Broadcasts can't send to cohorts with event conditions. Use a static or property-based cohort.",
        ],
        ['an unsaved cohort', cohort([], { id: 'new' }), 'Save the cohort first'],
        ['a deleted cohort', cohort([], { deleted: true }), 'Restore the cohort first'],
    ])('for %s', (_, input, expected) => {
        expect(cohortBroadcastDisabledReason(input)).toEqual(expected)
    })
})

describe('createCohortFormData', () => {
    const cohort = (overrides: Partial<CohortType> = {}): CohortType => ({
        id: 1,
        groups: [],
        filters: {
            properties: {
                type: FilterLogicalOperator.Or,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            { type: BehavioralFilterKey.Person, key: 'email', value: BehavioralEventType.HaveProperty },
                        ],
                    },
                ],
            },
            filterTestAccounts: true,
        },
        ...overrides,
    })

    it.each([
        ['a dynamic cohort', cohort(), {}, true],
        ['a static cohort built from criteria', cohort({ is_static: true }), { preserveStaticFilters: true }, true],
        ['a static cohort without criteria', cohort({ is_static: true }), {}, undefined],
    ])('serializes filterTestAccounts for %s', (_, input, options, expected) => {
        const filters = JSON.parse(createCohortFormData(input, options).get('filters') as string)
        expect(filters.filterTestAccounts).toEqual(expected)
    })
})

describe('isRecentPersonFilterUnsupported', () => {
    const definition = (propertyType: PropertyType): PropertyDefinition => ({
        id: 'property',
        name: 'property',
        property_type: propertyType,
    })

    it.each<
        [
            string,
            PropertyFilterType,
            PropertyOperator,
            PropertyFilterValue,
            PropertyDefinition | PropertyDefinitionState | null,
            boolean,
        ]
    >([
        [
            'text operator on a text property',
            PropertyFilterType.Person,
            PropertyOperator.IContains,
            'Chrome',
            definition(PropertyType.String),
            false,
        ],
        [
            'operator the text menu lacks',
            PropertyFilterType.Person,
            PropertyOperator.NotIn,
            ['Mac'],
            definition(PropertyType.String),
            true,
        ],
        [
            'absolute date on a date property',
            PropertyFilterType.Person,
            PropertyOperator.IsDateBefore,
            '2000-01-01',
            definition(PropertyType.DateTime),
            false,
        ],
        [
            'relative date on a date property',
            PropertyFilterType.Person,
            PropertyOperator.IsDateBefore,
            '-30d',
            definition(PropertyType.DateTime),
            true,
        ],
        [
            'text operator on a date property',
            PropertyFilterType.Person,
            PropertyOperator.IContains,
            '2000',
            definition(PropertyType.DateTime),
            true,
        ],
        [
            'date on person metadata',
            PropertyFilterType.PersonMetadata,
            PropertyOperator.IsDateAfter,
            '2020-01-01',
            definition(PropertyType.DateTime),
            false,
        ],
        [
            'type still loading',
            PropertyFilterType.Person,
            PropertyOperator.IsDateBefore,
            '2000-01-01',
            PropertyDefinitionState.Loading,
            true,
        ],
        [
            'type not found',
            PropertyFilterType.Person,
            PropertyOperator.IContains,
            'pro',
            PropertyDefinitionState.Missing,
            false,
        ],
        [
            'type lookup failed',
            PropertyFilterType.Person,
            PropertyOperator.IContains,
            'pro',
            PropertyDefinitionState.Error,
            false,
        ],
        [
            'event property',
            PropertyFilterType.Event,
            PropertyOperator.IContains,
            'Chrome',
            definition(PropertyType.String),
            true,
        ],
    ])('%s', (_, type, operator, value, lookupResult, expected) => {
        const filter = { type, key: 'property', operator, value } as AnyPropertyFilter
        expect(isRecentPersonFilterUnsupported(filter, () => lookupResult)).toBe(expected)
    })
})
