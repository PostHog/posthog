import { expectLogic } from 'kea-test-utils'
import { CountedPaginatedResponse } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveySchedule, SurveyType } from '~/types'

import { SURVEY_PAGE_SIZE } from './constants'
import { surveysLogic } from './surveysLogic'

const createTestSurvey = (id: string, name: string): Survey => ({
    id,
    name,
    description: '',
    type: SurveyType.Popover,
    linked_flag_id: null,
    linked_flag: null,
    targeting_flag: null,
    questions: [],
    conditions: null,
    appearance: null,
    created_at: '2024-01-01T00:00:00Z',
    created_by: null,
    start_date: null,
    end_date: null,
    archived: false,
    targeting_flag_filters: undefined,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
})

describe('surveysLogic', () => {
    describe('search functionality', () => {
        let logic: ReturnType<typeof surveysLogic.build>

        beforeEach(async () => {
            initKeaTests()
            logic = surveysLogic()
            logic.mount()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
            })

            await expectLogic(logic).toFinishAllListeners()
        })

        it('performs immediate frontend search and debounced backend search for large result sets', async () => {
            // Set up conditions that trigger backend search
            const apiResponse: CountedPaginatedResponse<Survey> = {
                count: 150, // More than SURVEY_PAGE_SIZE
                results: [
                    createTestSurvey('1', 'Test Survey 1'),
                    createTestSurvey('2', 'Another Survey'),
                    createTestSurvey('3', 'Test Survey 3'),
                ],
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: apiResponse.results,
                    surveysCount: apiResponse.count,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
            })
                .toDispatchActions(['loadSurveysSuccess'])
                .toFinishAllListeners()

            // When setting search term, frontend search happens immediately
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('Test')
            })
                .toMatchValues({
                    searchedSurveys: expect.arrayContaining([
                        expect.objectContaining({ id: '1' }),
                        expect.objectContaining({ id: '3' }),
                    ]),
                    searchTerm: 'Test',
                })
                // Backend search hasn't happened yet due to debounce
                .toNotHaveDispatchedActions(['loadSearchResults'])
                // Wait for debounce
                .delay(300)
                // Now the backend search should be triggered
                .toDispatchActions(['loadSearchResults'])
                .toFinishAllListeners()
        })

        it('performs only frontend search for small result sets', async () => {
            // 1. Set up initial state with a small number of surveys
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                    surveysCount: 50, // Less than SURVEY_PAGE_SIZE
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
            }).toFinishAllListeners()

            // 2. Perform search and verify frontend results
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('Test')
            })
                .toMatchValues({
                    searchedSurveys: [expect.objectContaining({ id: '1' })], // Only matching survey
                })
                .delay(400) // Wait longer than debounce
                .toNotHaveDispatchedActions(['loadSearchResults']) // No backend search
        })

        it('merges frontend and backend results without duplicates when backend search completes', async () => {
            const initialApiResponse: CountedPaginatedResponse<Survey> = {
                count: 150,
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            // First, load initial surveys and set search term
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: initialApiResponse.results,
                    surveysCount: initialApiResponse.count,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            }).toMatchValues({
                // Initially only shows frontend filtered results
                searchedSurveys: [expect.objectContaining({ id: '1' })],
            })

            // Then backend search completes
            const backendApiResponse: CountedPaginatedResponse<Survey> = {
                count: 2,
                results: [
                    createTestSurvey('1', 'Test Survey 1'), // Duplicate
                    createTestSurvey('3', 'Test Survey 3'), // New result
                ],
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSearchResultsSuccess({
                    ...logic.values.data,
                    searchSurveys: backendApiResponse.results,
                    searchSurveysCount: backendApiResponse.count,
                })
            }).toMatchValues({
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
                    expect.objectContaining({ id: '3' }),
                ]),
            })
        })

        it('handles empty search term', async () => {
            const apiResponse: CountedPaginatedResponse<Survey> = {
                count: 2,
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: apiResponse.results,
                    surveysCount: apiResponse.count,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('')
            })
                .toMatchValues({
                    searchedSurveys: apiResponse.results, // Should show all surveys
                    searchTerm: '',
                })
                .toNotHaveDispatchedActions(['loadSearchResults'])
        })

        it('handles search cancellation', async () => {
            jest.useFakeTimers()
            try {
                const apiResponse: CountedPaginatedResponse<Survey> = {
                    count: 150,
                    results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                    next: null,
                    previous: null,
                }

                logic.actions.loadSurveysSuccess({
                    surveys: apiResponse.results,
                    surveysCount: apiResponse.count,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                // Start a search
                logic.actions.setSearchTerm('test')
                // Cancel it before debounce timeout
                logic.actions.setSearchTerm('')
                // Fast forward past debounce time
                jest.advanceTimersByTime(300)
                await expectLogic(logic)
                    .toMatchValues({
                        searchedSurveys: apiResponse.results, // Should show all surveys
                        searchTerm: '',
                    })
                    .toNotHaveDispatchedActions(['loadSearchResults'])
            } finally {
                jest.useRealTimers()
            }
        })

        it('loads next page correctly', async () => {
            const initialApiResponse: CountedPaginatedResponse<Survey> = {
                count: 150,
                results: Array(SURVEY_PAGE_SIZE)
                    .fill(null)
                    .map((_, i) => createTestSurvey(i.toString(), `Survey ${i}`)),
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: initialApiResponse.results,
                    surveysCount: initialApiResponse.count,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
            }).toMatchValues({
                data: expect.objectContaining({
                    surveys: expect.arrayContaining(initialApiResponse.results),
                    surveysCount: initialApiResponse.count,
                }),
                hasNextPage: true,
            })

            const nextPageApiResponse: CountedPaginatedResponse<Survey> = {
                count: 150,
                results: Array(SURVEY_PAGE_SIZE)
                    .fill(null)
                    .map((_, i) =>
                        createTestSurvey((i + SURVEY_PAGE_SIZE).toString(), `Survey ${i + SURVEY_PAGE_SIZE}`)
                    ),
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadNextPageSuccess({
                    ...logic.values.data,
                    surveys: [...logic.values.data.surveys, ...nextPageApiResponse.results],
                    surveysCount: nextPageApiResponse.count,
                })
            }).toMatchValues({
                data: expect.objectContaining({
                    surveys: expect.arrayContaining([...initialApiResponse.results, ...nextPageApiResponse.results]),
                    surveysCount: nextPageApiResponse.count,
                }),
            })
        })
    })
})
