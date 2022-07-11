import { initKeaTests } from '~/test/init'
import { CohortLogicProps } from 'scenes/cohorts/cohortLogic'
import { expectLogic, partial } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { mockCohort } from '~/test/mocks'
import { teamLogic } from 'scenes/teamLogic'
import { api } from 'lib/api.mock'
import { cohortsModel } from '~/models/cohortsModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import {
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaGroupFilter,
    FilterLogicalOperator,
    PropertyOperator,
    TimeUnitType,
} from '~/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CRITERIA_VALIDATIONS, NEW_CRITERIA, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

describe('cohortEditLogic', () => {
    let logic: ReturnType<typeof cohortEditLogic.build>

    async function initCohortLogic(props: CohortLogicProps = { id: 'new' }): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
        featureFlagLogic.mount()
        await expectLogic(featureFlagLogic).toFinishAllListeners()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'update')
        api.get.mockClear()
        logic = cohortEditLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/cohorts': [mockCohort],
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            post: {
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
            patch: {
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
        })
        initKeaTests()
    })

    describe('initial load', () => {
        it('loads existing cohort on mount', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic).toDispatchActions(['fetchCohort'])

            expect(api.get).toBeCalledTimes(1)
        })

        it('loads new cohort on mount', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toBeCalledTimes(0)
        })

        it('loads new cohort on mount with undefined id', async () => {
            await initCohortLogic({ id: undefined })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toBeCalledTimes(0)
        })
    })

    it('delete cohort', async () => {
        await initCohortLogic({ id: 1 })
        await expectLogic(logic, async () => {
            await logic.actions.setCohort(mockCohort)
            await logic.actions.deleteCohort()
        })
            .toFinishAllListeners()
            .toDispatchActions(['setCohort', 'deleteCohort', router.actionCreators.push(urls.cohorts())])
            .toMatchValues({
                cohort: mockCohort,
            })
        expect(api.update).toBeCalledTimes(1)
    })

    describe('form validation', () => {
        beforeAll(() => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { 'cohort-filters': true })
        })

        it('save with valid cohort', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    filters: {
                        properties: {
                            ...mockCohort.filters.properties,
                            values: [
                                {
                                    id: '70427',
                                    type: FilterLogicalOperator.Or,
                                    values: [
                                        {
                                            type: BehavioralFilterKey.Behavioral,
                                            value: BehavioralEventType.PerformEvent,
                                            event_type: TaxonomicFilterGroupType.Events,
                                            time_value: 30,
                                            time_interval: TimeUnitType.Day,
                                            key: 'dashboard date range changed',
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toBeCalledTimes(1)
        })

        it('do not save with invalid name', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    name: '',
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })

        describe('negation errors', () => {
            it('do not save on OR operator', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    await logic.actions.setCohort({
                        ...mockCohort,
                        filters: {
                            properties: {
                                id: '39777',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        id: '70427',
                                        type: FilterLogicalOperator.Or,
                                        values: [
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: BehavioralEventType.PerformEvent,
                                                event_type: TaxonomicFilterGroupType.Events,
                                                time_value: 30,
                                                time_interval: TimeUnitType.Day,
                                                key: 'dashboard date range changed',
                                                negation: true,
                                            },
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: BehavioralEventType.PerformEvent,
                                                event_type: TaxonomicFilterGroupType.Events,
                                                time_value: 30,
                                                time_interval: TimeUnitType.Day,
                                                key: '$rageclick',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    })
                    await logic.actions.submitCohort()
                })
                    .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                    .toMatchValues({
                        cohortErrors: partial({
                            filters: {
                                properties: {
                                    values: [
                                        {
                                            id: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.",
                                            values: [
                                                {
                                                    value: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.",
                                                },
                                                {},
                                            ],
                                        },
                                    ],
                                },
                            },
                        }),
                    })
                expect(api.update).toBeCalledTimes(0)
            })

            it('do not save on less than one positive matching criteria', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    await logic.actions.setCohort({
                        ...mockCohort,
                        filters: {
                            properties: {
                                id: '39777',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        id: '70427',
                                        type: FilterLogicalOperator.And,
                                        values: [
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: BehavioralEventType.PerformEvent,
                                                event_type: TaxonomicFilterGroupType.Events,
                                                time_value: 30,
                                                time_interval: TimeUnitType.Day,
                                                key: 'dashboard date range changed',
                                                negation: true,
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    })
                    await logic.actions.submitCohort()
                })
                    .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                    .toMatchValues({
                        cohortErrors: partial({
                            filters: {
                                properties: {
                                    values: [
                                        {
                                            id: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.",
                                            values: [
                                                {
                                                    value: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.",
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                        }),
                    })
                expect(api.update).toBeCalledTimes(0)
            })

            it('do not save on criteria cancelling each other out', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    await logic.actions.setCohort({
                        ...mockCohort,
                        filters: {
                            properties: {
                                id: '39777',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        id: '70427',
                                        type: FilterLogicalOperator.And,
                                        values: [
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: BehavioralEventType.PerformEvent,
                                                event_type: TaxonomicFilterGroupType.Events,
                                                time_value: 30,
                                                time_interval: TimeUnitType.Day,
                                                key: 'dashboard date range changed',
                                                negation: true,
                                            },
                                            {
                                                type: BehavioralFilterKey.Behavioral,
                                                value: BehavioralEventType.PerformEvent,
                                                event_type: TaxonomicFilterGroupType.Events,
                                                time_value: 30,
                                                time_interval: TimeUnitType.Day,
                                                key: 'dashboard date range changed',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    })
                    await logic.actions.submitCohort()
                })
                    .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                    .toMatchValues({
                        cohortErrors: partial({
                            filters: {
                                properties: {
                                    values: [
                                        {
                                            id: 'These criteria cancel each other out, and would result in no matching persons.',
                                            values: [
                                                {
                                                    value: 'These criteria cancel each other out, and would result in no matching persons.',
                                                },
                                                {
                                                    value: 'These criteria cancel each other out, and would result in no matching persons.',
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                        }),
                    })
                expect(api.update).toBeCalledTimes(0)
            })
        })

        it('do not save on invalid lower and upper bound period values - perform event regularly', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    filters: {
                        properties: {
                            id: '26585',
                            type: FilterLogicalOperator.Or,
                            values: [
                                {
                                    id: '6',
                                    type: FilterLogicalOperator.Or,
                                    values: [
                                        {
                                            type: BehavioralFilterKey.Behavioral,
                                            value: BehavioralLifecycleType.PerformEventRegularly,
                                            event_type: TaxonomicFilterGroupType.Events,
                                            time_value: 1,
                                            time_interval: TimeUnitType.Day,
                                            operator: PropertyOperator.Exact,
                                            operator_value: 5,
                                            min_periods: 6,
                                            total_periods: 5,
                                            negation: false,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
                await logic.actions.submitCohort()
            })
                .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                .toMatchValues({
                    cohortErrors: partial({
                        filters: {
                            properties: {
                                values: [
                                    {
                                        values: [
                                            {
                                                id: 'The lower bound period value must not be greater than the upper bound value.',
                                                min_periods:
                                                    'The lower bound period value must not be greater than the upper bound value.',
                                                total_periods:
                                                    'The lower bound period value must not be greater than the upper bound value.',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    }),
                })
            expect(api.update).toBeCalledTimes(0)
        })

        it('do not save on invalid lower and upper bound period values - perform events in sequence', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    filters: {
                        properties: {
                            type: FilterLogicalOperator.Or,
                            values: [
                                {
                                    type: FilterLogicalOperator.Or,
                                    values: [
                                        {
                                            type: BehavioralFilterKey.Behavioral,
                                            value: BehavioralEventType.PerformSequenceEvents,
                                            negation: false,
                                            key: '$groupidentify',
                                            event_type: TaxonomicFilterGroupType.Events,
                                            time_value: '28',
                                            time_interval: TimeUnitType.Day,
                                            seq_event: '$groupidentify',
                                            seq_time_value: '30',
                                            seq_time_interval: TimeUnitType.Day,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
                await logic.actions.submitCohort()
            })
                .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                .toMatchValues({
                    cohortErrors: partial({
                        filters: {
                            properties: {
                                values: [
                                    {
                                        values: [
                                            {
                                                id: 'The lower bound period sequential time value must not be greater than the upper bound time value.',
                                                time_value:
                                                    'The lower bound period sequential time value must not be greater than the upper bound time value.',
                                                seq_time_value:
                                                    'The lower bound period sequential time value must not be greater than the upper bound time value.',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    }),
                })
            expect(api.update).toBeCalledTimes(0)
        })

        describe('empty input errors', () => {
            Object.entries(ROWS).forEach(([key, row]) => {
                it(`${key} row missing all required fields`, async () => {
                    await initCohortLogic({ id: 1 })
                    await expectLogic(logic, async () => {
                        await logic.actions.setCohort({
                            ...mockCohort,
                            filters: {
                                properties: {
                                    id: '26585',
                                    type: FilterLogicalOperator.Or,
                                    values: [
                                        {
                                            id: '6',
                                            type: FilterLogicalOperator.Or,
                                            values: [
                                                {
                                                    type: row.type,
                                                    value: row.value,
                                                    ...Object.fromEntries(
                                                        row.fields
                                                            .filter(({ fieldKey }) => !!fieldKey)
                                                            .map(({ fieldKey }) => [fieldKey, undefined])
                                                    ),
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                        })
                        await logic.actions.submitCohort()
                    })
                        .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
                        .toMatchValues({
                            cohortErrors: partial({
                                filters: {
                                    properties: {
                                        values: [
                                            {
                                                values: [
                                                    partial(
                                                        Object.fromEntries(
                                                            row.fields
                                                                .filter(({ fieldKey }) => !!fieldKey)
                                                                .map(({ fieldKey, type }) => [
                                                                    fieldKey,
                                                                    CRITERIA_VALIDATIONS[type](undefined),
                                                                ])
                                                        )
                                                    ),
                                                ],
                                            },
                                        ],
                                    },
                                },
                            }),
                        })
                    expect(api.update).toBeCalledTimes(0)
                })
            })
        })

        it('can save existing static cohort with empty csv', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    is_static: true,
                    groups: [],
                    csv: undefined,
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toBeCalledTimes(1)
        })

        it('do not save static cohort with empty csv', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic, async () => {
                await logic.actions.setCohort({
                    ...mockCohort,
                    is_static: true,
                    groups: [],
                    csv: undefined,
                    id: 'new',
                })
                await logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toBeCalledTimes(0)
        })
    })

    describe('mutate filters', () => {
        beforeAll(async () => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { 'cohort-filters': true })
        })

        beforeEach(async () => {
            await initCohortLogic({ id: 1 })
        })

        it('duplicate group', async () => {
            await expectLogic(logic, () => {
                logic.actions.duplicateFilter(0)
            })
                .toDispatchActions(['duplicateFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial(mockCohort.filters.properties.values[0]),
                                    partial(mockCohort.filters.properties.values[0]),
                                ],
                            }),
                        },
                    }),
                })
        })

        it('remove group', async () => {
            await expectLogic(logic, () => {
                logic.actions.removeFilter(0)
            })
                .toDispatchActions(['removeFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [],
                            }),
                        },
                    }),
                })
        })

        it('add group', async () => {
            await expectLogic(logic, () => {
                logic.actions.addFilter()
            })
                .toDispatchActions(['addFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial(mockCohort.filters.properties.values[0]),
                                    partial({
                                        type: FilterLogicalOperator.Or,
                                        values: [NEW_CRITERIA],
                                    }),
                                ],
                            }),
                        },
                    }),
                })
        })

        it('duplicate criteria', async () => {
            await expectLogic(logic, () => {
                logic.actions.duplicateFilter(0, 0)
            })
                .toDispatchActions(['duplicateFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial({
                                        values: [
                                            partial(
                                                (mockCohort.filters.properties.values[0] as CohortCriteriaGroupFilter)
                                                    .values[0]
                                            ),
                                            partial(
                                                (mockCohort.filters.properties.values[0] as CohortCriteriaGroupFilter)
                                                    .values[0]
                                            ),
                                        ],
                                    }),
                                ],
                            }),
                        },
                    }),
                })
        })

        it('remove criteria', async () => {
            await expectLogic(logic, () => {
                logic.actions.removeFilter(0, 0)
            })
                .toDispatchActions(['removeFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial({
                                        values: [],
                                    }),
                                ],
                            }),
                        },
                    }),
                })
        })

        it('add criteria', async () => {
            await expectLogic(logic, () => {
                logic.actions.addFilter(0)
            })
                .toDispatchActions(['addFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial({
                                        values: [
                                            partial(
                                                (mockCohort.filters.properties.values[0] as CohortCriteriaGroupFilter)
                                                    .values[0]
                                            ),
                                            NEW_CRITERIA,
                                        ],
                                    }),
                                ],
                            }),
                        },
                    }),
                })
        })

        it('set outer logical operator', async () => {
            await expectLogic(logic, () => {
                logic.actions.setOuterGroupsType(FilterLogicalOperator.And)
            })
                .toDispatchActions(['setOuterGroupsType'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                type: FilterLogicalOperator.And,
                            }),
                        },
                    }),
                })
        })

        it('set inner logical operator', async () => {
            await expectLogic(logic, () => {
                logic.actions.setInnerGroupType(FilterLogicalOperator.And, 0)
            })
                .toDispatchActions(['setInnerGroupType'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [
                                    partial({
                                        type: FilterLogicalOperator.And,
                                    }),
                                ],
                            }),
                        },
                    }),
                })
        })
    })
})
