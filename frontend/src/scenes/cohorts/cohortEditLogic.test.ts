import { api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { scrollToFormError } from 'lib/forms/scrollToFormError'
import { CohortLogicProps, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { CRITERIA_VALIDATIONS, NEW_CRITERIA, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { ActorsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'
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

import type { CohortUsedInResponseApi } from 'products/cohorts/frontend/generated/api.schemas'

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

const mockUsedInResponse: CohortUsedInResponseApi = {
    feature_flags: {
        results: [{ id: 7, key: 'my-flag', name: 'My Flag' }],
        total: 1,
        has_more: false,
    },
    insights: { results: [], total: 0, has_more: false },
    cohorts: { results: [], total: 0, has_more: false },
}

describe('cohortEditLogic', () => {
    let logic: ReturnType<typeof cohortEditLogic.build>
    async function initCohortLogic(props: CohortLogicProps = { id: 'new' }): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'update')
        jest.spyOn(api, 'create')
        api.get.mockClear()
        api.create.mockClear()
        logic = cohortEditLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(async () => {
        // Persisted column selection lives in localStorage keyed by cohort id — clear it so
        // column state doesn't leak between tests that reuse the same cohort id.
        window.localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': toPaginatedResponse([mockCohort]),
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
                '/api/projects/:team_id/cohorts/:id/used_in/': mockUsedInResponse,
            },
            post: {
                '/api/projects/:team_id/cohorts/': mockCohort,
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
            },
            patch: {
                '/api/projects/:team_id/cohorts/:id/': mockCohort,
            },
        })
        initKeaTests()
    })

    describe('initial load', () => {
        it('loads existing cohort on mount', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic).toDispatchActions(['fetchCohort'])

            // One call for the cohort itself, one for its used-in references
            expect(api.get).toHaveBeenCalledTimes(2)
        })

        it('loads used-in references on mount before the cohort has resolved', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic).toDispatchActions(['loadUsedIn', 'loadUsedInSuccess'])

            expect(logic.values.usedIn).toEqual(mockUsedInResponse)
        })

        it('swallows used-in 404s without reporting them', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/cohorts/:id/used_in/': () => [404, { detail: 'Not found.' }],
                },
            })
            await initCohortLogic({ id: 1 })
            // The loader swallows the error and returns a value, so Success (not Failure) fires.
            await expectLogic(logic).toDispatchActions(['loadUsedIn', 'loadUsedInSuccess'])

            expect(logic.values.usedIn).toEqual(null)
            expect(posthog.captureException).not.toHaveBeenCalled()
        })

        it('reports non-404 used-in failures', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/cohorts/:id/used_in/': () => [500, { detail: 'Server error' }],
                },
            })
            await initCohortLogic({ id: 1 })
            // The loader still returns a value on non-404 errors, so Success (not Failure) fires.
            await expectLogic(logic).toDispatchActions(['loadUsedIn', 'loadUsedInSuccess'])

            expect(logic.values.usedIn).toEqual(null)
            expect(posthog.captureException).toHaveBeenCalled()
        })

        it('keeps the previously loaded value when a refresh fails', async () => {
            await initCohortLogic({ id: 1 })
            await expectLogic(logic).toDispatchActions(['loadUsedIn', 'loadUsedInSuccess'])
            expect(logic.values.usedIn).toEqual(mockUsedInResponse)

            useMocks({
                get: {
                    '/api/projects/:team_id/cohorts/:id/used_in/': () => [500, { detail: 'Server error' }],
                },
            })
            await expectLogic(logic, () => {
                logic.actions.loadUsedIn()
            }).toDispatchActions(['loadUsedIn', 'loadUsedInSuccess'])

            // The failed refresh returns the prior value instead of blanking the banner.
            expect(logic.values.usedIn).toEqual(mockUsedInResponse)
        })

        it('loads new cohort on mount', async () => {
            await initCohortLogic({ id: 'new' })
            await expectLogic(logic).toDispatchActions(['setCohort'])

            expect(api.get).toHaveBeenCalledTimes(0)
            expect(logic.values.staticCohortMode).toEqual('people')
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
            })
                .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess', 'saveCohortSuccess'])
                .toNotHaveDispatchedActions(['loadUsedIn'])
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

        describe('negation validation', () => {
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
                                            id: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND).",
                                            values: [
                                                {
                                                    value: "'Did not complete event' is a negative cohort criteria. Negation criteria can only be used when matching all criteria (AND).",
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

            it('saves a cohort with only negative matching criteria', async () => {
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
                    .toDispatchActions(['setCohort', 'submitCohort', 'submitCohortSuccess', 'saveCohortSuccess'])
                    .toMatchValues({
                        cohortErrors: {},
                    })
                expect(api.update).toHaveBeenCalledTimes(1)
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
                                                                        !!fieldKey &&
                                                                        fieldKey !== 'event_filters' &&
                                                                        fieldKey !== 'explicit_datetime_to'
                                                                ) // event_filters and explicit_datetime_to are optional
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
                    filters: { properties: {} as any },
                    csv: undefined,
                })
                logic.actions.setStaticCohortMode('people')
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'setStaticCohortMode', 'submitCohort', 'submitCohortSuccess'])
            expect(api.update).toHaveBeenCalledTimes(1)
        })

        it('can create static cohort from criteria without csv', async () => {
            await initCohortLogic({ id: 'new' })
            const createdCohort = {
                ...mockCohort,
                id: 2,
                name: 'Static from criteria',
                is_static: true,
            }
            const createSpy = jest.spyOn(api.cohorts, 'create').mockResolvedValue(createdCohort)
            const setTimeoutSpy = jest.spyOn(window, 'setTimeout').mockImplementation(() => 0 as never)

            await expectLogic(logic, async () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    id: 'new',
                    name: 'Static from criteria',
                    is_static: true,
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
                logic.actions.setStaticCohortMode('criteria')
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'setStaticCohortMode', 'submitCohort', 'submitCohortSuccess'])

            expect(createSpy).toHaveBeenCalledTimes(1)
            const createPayload = createSpy.mock.calls[0][0] as FormData
            expect(createPayload.get('is_static')).toEqual('true')
            expect(createPayload.get('filters')).toContain('"values"')
            expect(createPayload.get('filters')).not.toContain('"properties":{}')

            setTimeoutSpy.mockRestore()
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
                logic.actions.setStaticCohortMode('people')
                logic.actions.submitCohort()
            }).toDispatchActions(['setCohort', 'setStaticCohortMode', 'submitCohort'])
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

    describe('query state and column configuration', () => {
        it('preserves custom column configuration when setCohort is called', async () => {
            await initCohortLogic({ id: 1 })

            // Set custom columns via setQuery
            const customColumns = ['person_display_name -- Person', 'id', 'created_at', 'properties.$browser']
            const testQuery: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    fixedProperties: [
                        { type: PropertyFilterType.Cohort, key: 'id', value: 1, operator: PropertyOperator.In },
                    ],
                    select: customColumns,
                },
                full: true,
                showPropertyFilter: false,
                showEventFilter: false,
            }
            await expectLogic(logic, () => {
                logic.actions.setQuery(testQuery)
            })
                .toDispatchActions(['setQuery'])
                .toMatchValues({
                    query: testQuery,
                })

            // Now call setCohort (simulating what happens after saving)
            await expectLogic(logic, () => {
                logic.actions.setCohort(mockCohort)
            })
                .toDispatchActions(['setCohort'])
                .toMatchValues({
                    query: partial({
                        source: partial({
                            select: customColumns, // Custom columns should be preserved
                        }),
                    }),
                })
        })

        it('uses default columns when no custom columns have been set', async () => {
            await initCohortLogic({ id: 1 })

            // Call setCohort without setting custom columns first
            await expectLogic(logic, () => {
                logic.actions.setCohort(mockCohort)
            })
                .toDispatchActions(['setCohort'])
                .toMatchValues({
                    query: partial({
                        source: partial({
                            // For non-static cohorts, default is without the delete column
                            select: ['person_display_name -- Person', 'id', 'created_at'],
                        }),
                    }),
                })
        })

        it('preserves custom columns after saving cohort (simulating saveCohort flow)', async () => {
            await initCohortLogic({ id: 1 })

            // First, set the cohort (this happens on initial load via fetchCohort)
            await expectLogic(logic).toFinishAllListeners()

            // User configures custom columns via the "Configure columns" UI
            const customColumns = ['person_display_name -- Person', 'id', 'properties.$browser', 'properties.$os']
            const testQuery: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    fixedProperties: [
                        { type: PropertyFilterType.Cohort, key: 'id', value: 1, operator: PropertyOperator.In },
                    ],
                    select: customColumns,
                },
                full: true,
                showPropertyFilter: false,
                showEventFilter: false,
            }
            await expectLogic(logic, () => {
                logic.actions.setQuery(testQuery)
            }).toDispatchActions(['setQuery'])

            // Verify custom columns are set
            expect((logic.values.query.source as ActorsQuery).select).toEqual(customColumns)

            // User saves the cohort - this triggers setCohort with the updated cohort from API
            // (simulating what happens in saveCohort loader after API call)
            await expectLogic(logic, () => {
                logic.actions.setCohort({
                    ...mockCohort,
                    is_calculating: false,
                    last_calculation: '2024-01-01T00:00:00Z',
                })
            }).toDispatchActions(['setCohort'])

            // Custom columns should still be preserved after save
            expect((logic.values.query.source as ActorsQuery).select).toEqual(customColumns)
        })

        const defaultColumns = ['person_display_name -- Person', 'id', 'created_at']
        const customColumns = [...defaultColumns, 'properties.$browser']

        it.each([
            ['the same cohort restores the persisted columns', 1, customColumns],
            ["another cohort ignores the first cohort's columns and uses defaults", 2, defaultColumns],
        ])('after a refresh (remount), %s', async (_name, remountId, expectedSelect) => {
            await initCohortLogic({ id: 1 })

            await expectLogic(logic, () => {
                logic.actions.setQuery({
                    ...logic.values.query,
                    source: { ...(logic.values.query.source as ActorsQuery), select: customColumns },
                } as DataTableNode)
            }).toDispatchActions(['setQuery'])

            // Simulate a refresh: tear down and rebuild the logic
            logic.unmount()
            logic = cohortEditLogic({ id: remountId })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect((logic.values.effectiveQuery.source as ActorsQuery).select).toEqual(expectedSelect)
        })

        it('does not carry columns from one unsaved draft cohort over to the next', async () => {
            await initCohortLogic({ id: 'new' })

            await expectLogic(logic, () => {
                logic.actions.setQuery({
                    ...logic.values.query,
                    source: { ...(logic.values.query.source as ActorsQuery), select: customColumns },
                } as DataTableNode)
            }).toDispatchActions(['setQuery'])

            // Abandon the draft and start a fresh one — both share the 'new' logic key
            logic.unmount()
            logic = cohortEditLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect((logic.values.effectiveQuery.source as ActorsQuery).select).toEqual(defaultColumns)
        })
    })

    describe('cohort duplication', () => {
        it('duplicate static cohort as static', async () => {
            await initCohortLogic({ id: 1 })

            const staticCohort = {
                ...mockCohort,
                id: 1,
                name: 'Static Cohort',
                is_static: true,
            }

            const duplicatedCohort = {
                ...staticCohort,
                id: 2,
                name: 'Static Cohort (static copy)',
            }

            jest.spyOn(api, 'create').mockResolvedValue(duplicatedCohort)

            await expectLogic(logic, () => {
                logic.actions.setCohort(staticCohort)
                logic.actions.duplicateCohort(true)
            }).toFinishAllListeners()

            expect(api.create).toHaveBeenCalledWith('api/cohort', {
                is_static: true,
                name: 'Static Cohort (static copy)',
                query: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT person_id FROM static_cohort_people WHERE cohort_id = 1',
                },
            })
        })

        it('duplicate dynamic cohort as static', async () => {
            await initCohortLogic({ id: 1 })

            const dynamicCohort = {
                ...mockCohort,
                id: 1,
                name: 'Dynamic Cohort',
                is_static: false,
            }

            const duplicatedCohort = {
                ...dynamicCohort,
                id: 2,
                name: 'Dynamic Cohort (static copy)',
                is_static: true,
            }

            jest.spyOn(api, 'create').mockResolvedValue(duplicatedCohort)

            await expectLogic(logic, () => {
                logic.actions.setCohort(dynamicCohort)
                logic.actions.duplicateCohort(true)
            }).toFinishAllListeners()

            expect(api.create).toHaveBeenCalledWith('api/cohort', {
                is_static: true,
                name: 'Dynamic Cohort (static copy)',
                query: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT person_id FROM cohort_people WHERE cohort_id = 1',
                },
            })
        })

        it('duplicate dynamic cohort as dynamic', async () => {
            await initCohortLogic({ id: 1 })

            const dynamicCohort = {
                ...mockCohort,
                id: 1,
                name: 'Dynamic Cohort',
                is_static: false,
                filters: {
                    properties: {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                sort_key: 'mocked-uuid',
                                type: FilterLogicalOperator.Or,
                                values: [
                                    {
                                        sort_key: 'mocked-uuid',
                                        explicit_datetime: '-30d',
                                        type: BehavioralFilterKey.Behavioral,
                                        value: BehavioralEventType.PerformEvent,
                                        event_type: TaxonomicFilterGroupType.Events,
                                        time_value: 30,
                                        time_interval: TimeUnitType.Day,
                                        key: '$pageview',
                                    },
                                ],
                            },
                        ],
                    },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setCohort(dynamicCohort)
                logic.actions.duplicateCohort(false)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    // The duplication should complete without errors
                    cohort: partial(dynamicCohort),
                })
        }, 15000)
    })

    describe('active tab URL routing', () => {
        beforeEach(async () => {
            await initCohortLogic({ id: 1 })
            router.actions.replace(urls.cohort(1))
        })

        it('defaults to overview when no hash is set', async () => {
            await expectLogic(logic).toMatchValues({ activeTab: 'overview' })
        })

        it('writes #tab=history when switching to history', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveTab('history')
            }).toFinishAllListeners()
            expect(router.values.hashParams.tab).toBe('history')
        })

        it('strips the tab key from the hash when switching back to overview', async () => {
            logic.actions.setActiveTab('history')
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.hashParams.tab).toBe('history')

            await expectLogic(logic, () => {
                logic.actions.setActiveTab('overview')
            }).toFinishAllListeners()
            expect(router.values.hashParams.tab).toBeUndefined()
        })

        it('reads the tab from the URL on navigation', async () => {
            router.actions.replace(urls.cohort(1), {}, { tab: 'history' })
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ activeTab: 'history' })
        })

        it('falls back to overview when the hash tab value is unrecognized', async () => {
            router.actions.replace(urls.cohort(1), {}, { tab: 'garbage' })
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ activeTab: 'overview' })
        })
    })

    describe('new cohort hash hygiene', () => {
        it('clears a stale #tab=history hash on mount and resets activeTab to overview', async () => {
            router.actions.replace(urls.cohort('new'), {}, { tab: 'history' })
            await initCohortLogic({ id: 'new' })
            expect(router.values.hashParams.tab).toBeUndefined()
            // Without resetting activeTab, the user would land on a blank screen for new cohorts:
            // overview is hidden via `display:none` while history requires a saved cohort to render.
            expect(logic.values.activeTab).toBe('overview')
        })
    })
})
