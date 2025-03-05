import { expectLogic } from 'kea-test-utils'
import { CountedPaginatedResponse } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveySchedule, SurveyType } from '~/types'

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
            const surveys: CountedPaginatedResponse<Survey> = {
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
                logic.actions.loadSurveysSuccess(surveys)
            })
                .toDispatchActions(['loadSurveysSuccess'])
                .toFinishAllListeners()

            const mockedApiCall = jest.fn().mockResolvedValue([200, surveys])
            useMocks({
                get: {
                    '/api/projects/:team/surveys/': mockedApiCall,
                },
            })

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
                .toNotHaveDispatchedActions(['loadBackendSearchResults'])
                // Wait for debounce
                .delay(300)
                // Now the backend search should be triggered
                .toDispatchActions(['loadBackendSearchResults'])
                .toFinishAllListeners()

            expect(mockedApiCall).toHaveBeenCalled()
        })

        it('performs only frontend search for small result sets', async () => {
            const surveys: CountedPaginatedResponse<Survey> = {
                count: 50, // Less than SURVEY_PAGE_SIZE
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            // mock API call
            const mockedApiCall = jest.fn()
            useMocks({
                get: {
                    '/api/projects/:team/surveys/': mockedApiCall,
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess(surveys)
                logic.actions.setSearchTerm('Test')
            })
                .toMatchValues({
                    searchedSurveys: [surveys.results[0]], // Only the matching survey
                    searchTerm: 'Test',
                })
                .delay(300)
            // make sure we are NOT makign the API call

            expect(mockedApiCall).not.toHaveBeenCalled()
        })

        it('merges frontend and backend results without duplicates when backend search completes', async () => {
            const initialSurveys: CountedPaginatedResponse<Survey> = {
                count: 150,
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            // First, load initial surveys and set search term
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess(initialSurveys)
                logic.actions.setSearchTerm('Test')
            }).toMatchValues({
                // Initially only shows frontend filtered results
                searchedSurveys: [expect.objectContaining({ id: '1' })],
            })

            // Then backend search completes
            const backendResults: CountedPaginatedResponse<Survey> = {
                count: 2,
                results: [
                    createTestSurvey('1', 'Test Survey 1'), // Duplicate
                    createTestSurvey('3', 'Test Survey 3'), // New result
                ],
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadBackendSearchResultsSuccess(backendResults)
            }).toMatchValues({
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
                    expect.objectContaining({ id: '3' }),
                ]),
            })
        })

        it('handles empty search term', async () => {
            const surveys: CountedPaginatedResponse<Survey> = {
                count: 2,
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess(surveys)
                logic.actions.setSearchTerm('')
            })
                .toMatchValues({
                    searchedSurveys: surveys.results, // Should show all surveys
                    searchTerm: '',
                })
                .toNotHaveDispatchedActions(['loadBackendSearchResults'])
        })

        it('handles search cancellation', async () => {
            jest.useFakeTimers()

            const surveys: CountedPaginatedResponse<Survey> = {
                count: 150,
                results: [createTestSurvey('1', 'Test Survey 1'), createTestSurvey('2', 'Another Survey')],
                next: null,
                previous: null,
            }

            logic.actions.loadSurveysSuccess(surveys)

            // Start a search
            logic.actions.setSearchTerm('test')

            // Cancel it before debounce timeout
            logic.actions.setSearchTerm('')

            // Fast forward past debounce time
            jest.advanceTimersByTime(300)

            await expectLogic(logic)
                .toMatchValues({
                    searchedSurveys: surveys.results, // Should show all surveys
                    searchTerm: '',
                })
                .toNotHaveDispatchedActions(['loadBackendSearchResults'])

            jest.useRealTimers()
        })
    })
})
