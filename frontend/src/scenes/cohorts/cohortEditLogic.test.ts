import { api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import { v4 as uuidv4 } from 'uuid'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { scrollToFormError } from 'lib/forms/scrollToFormError'
import { CRITERIA_VALIDATIONS, NEW_CRITERIA, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { CohortLogicProps, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'
import {
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaGroupFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

jest.mock('uuid', () => ({
    v4: jest.fn().mockReturnValue('mocked-uuid'),
}))

jest.mock('lib/forms/scrollToFormError', () => ({
    scrollToFormError: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

describe('cohortEditLogic', () => {
    let logic: ReturnType<typeof cohortEditLogic.build>
    async function initCohortLogic(props: CohortLogicProps = { id: 'new' }): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
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

            expect(api.get).toHaveBeenCalledTimes(1)
        })

        it('loads new cohort on mount', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toHaveBeenCalledTimes(0)
        })

        it('loads new cohort on mount with undefined id', async () => {
            await initCohortLogic({ id: undefined })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toHaveBeenCalledTimes(0)
        })
    })

    it('delete cohort', async () => {
        await initCohortLogic({ id: 1 })
        await expectLogic(logic, async () => {
            logic.actions.setCohort(mockCohort)
            logic.actions.deleteCohort()
        })
            .toFinishAllListeners()
            .toDispatchActions(['setCohort', 'deleteCohort', router.actionCreators.push(urls.cohorts())])
        expect(api.update).toHaveBeenCalledTimes(1)
    })

    it('restore cohort', async () => {
        await initCohortLogic({ id: 1 })
        await expectLogic(logic, async () => {
            logic.actions.setCohort({ ...mockCohort, deleted: true })
            logic.actions.restoreCohort()
        })
            .toFinishAllListeners()
            .toDispatchActions(['setCohort', 'restoreCohort'])
        expect(api.update).toHaveBeenCalledTimes(1)
        expect(api.update).toHaveBeenCalledWith(
            expect.anything(),
            {
                deleted: false,
            },
            expect.anything()
        )
    })

    describe('form validation', () => {
        it('save with valid cohort', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
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
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toHaveBeenCalledTimes(1)
        })

        it('do not save with invalid name', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    name: '',
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortFailure'])
            expect(api.update).toHaveBeenCalledTimes(0)
        })

        describe('negation errors', () => {
            it('do not save on OR operator', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    logic.actions.setCohort({
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
                    logic.actions.submitCohort()
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
                expect(api.update).toHaveBeenCalledTimes(0)
            })

            it('do not save on less than one positive matching criteria', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    logic.actions.setCohort({
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
                    logic.actions.submitCohort()
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
                expect(api.update).toHaveBeenCalledTimes(0)
            })

            it('do not save on criteria cancelling each other out', async () => {
                await initCohortLogic({ id: 1 })
                await expectLogic(logic, async () => {
                    logic.actions.setCohort({
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
                    logic.actions.submitCohort()
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
                expect(api.update).toHaveBeenCalledTimes(0)
            })
        })

        it('do not save on invalid lower and upper bound period values - perform event regularly', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
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
                logic.actions.submitCohort()
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
            expect(api.update).toHaveBeenCalledTimes(0)
        })

        it('do not save on invalid lower and upper bound period values - perform events in sequence', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
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
                logic.actions.submitCohort()
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
            expect(api.update).toHaveBeenCalledTimes(0)
        })

        it('do not save on partial event filters', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
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
                                            explicit_datetime: '-14d',
                                            key: 'dashboard date range changed',
                                            event_filters: [
                                                {
                                                    key: '$browser',
                                                    value: null,
                                                    type: PropertyFilterType.Event,
                                                    operator: PropertyOperator.Exact,
                                                },
                                            ],
                                        },
                                        {
                                            type: BehavioralFilterKey.Behavioral,
                                            value: BehavioralEventType.PerformEvent,
                                            event_type: TaxonomicFilterGroupType.Events,
                                            time_value: '1',
                                            time_interval: TimeUnitType.Day,
                                            key: '$rageclick',
                                            negation: true,
                                            event_filters: [
                                                {
                                                    key: '$browser',
                                                    value: null,
                                                    type: PropertyFilterType.Event,
                                                    operator: PropertyOperator.Exact,
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
                logic.actions.submitCohort()
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
                                                event_filters: 'Event filters cannot be empty.',
                                                id: 'Event filters cannot be empty.',
                                            },
                                            {
                                                event_filters: 'Event filters cannot be empty.',
                                                id: 'Event filters cannot be empty.',
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    }),
                })
            expect(api.update).toHaveBeenCalledTimes(0)
        })

        describe('empty input errors', () => {
            Object.entries(ROWS).forEach(([key, row]) => {
                it(`${key} row missing all required fields`, async () => {
                    await initCohortLogic({ id: 1 })
                    await expectLogic(logic, async () => {
                        logic.actions.setCohort({
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
                        logic.actions.submitCohort()
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
                                                                .filter(
                                                                    ({ fieldKey }) =>
                                                                        !!fieldKey && fieldKey !== 'event_filters'
                                                                ) // event_filters are optional
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
                    expect(api.update).toHaveBeenCalledTimes(0)
                })
            })
        })

        it('can save existing static cohort with empty csv', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    is_static: true,
                    groups: [],
                    csv: undefined,
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toHaveBeenCalledTimes(1)
        })

        it('do not save static cohort with empty csv', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic, async () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    is_static: true,
                    groups: [],
                    csv: undefined,
                    id: 'new',
                })
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'submitCohort'])
            expect(api.update).toHaveBeenCalledTimes(0)
        })

        it('calls scrollToFormError with fallback message on submitCohortFailure', async () => {
            await initCohortLogic({ id: 1 })
            const mockScrollToFormError = scrollToFormError as jest.Mock

            const testError = new Error('Test cohort submission error')
            const testErrors = { name: 'Invalid name' }

            await expectLogic(logic, async () => {
                logic.actions.submitCohortFailure(testError, testErrors)
            }).toDispatchActions(['submitCohortFailure'])

            expect(mockScrollToFormError).toHaveBeenCalledWith({
                extraErrorSelectors: ['.CohortCriteriaRow__Criteria--error'],
                fallbackErrorMessage:
                    'There was an error submitting this cohort. Make sure the cohort filters are correct.',
            })
        })
    })

    describe('mutate filters', () => {
        beforeEach(async () => {
            await initCohortLogic({ id: 1 })
        })

        it('duplicate group', async () => {
            const expectedGroupValue = partial({
                ...mockCohort.filters.properties.values[0],
                values: [
                    {
                        ...(mockCohort.filters.properties.values[0] as CohortCriteriaGroupFilter).values[0],
                        explicit_datetime: '-30d',
                        sort_key: uuidv4(),
                    },
                ],
            }) // Backwards compatible processing adds explicit_datetime

            await expectLogic(logic, () => {
                logic.actions.duplicateFilter(0)
            })
                .toDispatchActions(['duplicateFilter'])
                .toMatchValues({
                    cohort: partial({
                        filters: {
                            properties: partial({
                                values: [expectedGroupValue, expectedGroupValue],
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
                                    partial({
                                        ...mockCohort.filters.properties.values[0],
                                        values: [
                                            {
                                                ...(
                                                    mockCohort.filters.properties.values[0] as CohortCriteriaGroupFilter
                                                ).values[0],
                                                explicit_datetime: '-30d',
                                                sort_key: uuidv4(),
                                            },
                                        ],
                                    }), // Backwards compatible processing adds explicit_datetime
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
                                            { ...NEW_CRITERIA, sort_key: uuidv4() },
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
