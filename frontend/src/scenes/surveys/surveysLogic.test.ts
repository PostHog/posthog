import { expectLogic } from 'kea-test-utils'

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

        it('performs frontend search immediately', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [
                        createTestSurvey('1', 'Test Survey 1'),
                        createTestSurvey('2', 'Another Survey'),
                        createTestSurvey('3', 'Test Survey 3'),
                    ],
                    surveysCount: 150,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            }).toMatchValues({
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
                    expect.objectContaining({ id: '3' }),
                ]),
            })
        })

        it('triggers backend search after debounce for large datasets', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey')],
                    surveysCount: 150, // > SURVEY_PAGE_SIZE
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            })
                .delay(400)
                .toDispatchActions(['loadSearchResults'])
        })

        it('performs only frontend search for small datasets', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey')],
                    surveysCount: 50, // < SURVEY_PAGE_SIZE
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            })
                .delay(400)
                .toNotHaveDispatchedActions(['loadSearchResults'])
        })

        it('merges and deduplicates frontend and backend results', async () => {
            // Set initial state with frontend results and trigger search
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey'), createTestSurvey('2', 'Another Test')],
                    surveysCount: 150,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            }).toMatchValues({
                // Verify frontend search results first
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
                    expect.objectContaining({ id: '2' }),
                ]),
            })

            // Then simulate backend search completion
            await expectLogic(logic, () => {
                logic.actions.loadSearchResultsSuccess({
                    ...logic.values.data,
                    searchSurveys: [createTestSurvey('1', 'Test Survey'), createTestSurvey('3', 'New Test')],
                    searchSurveysCount: 2,
                })
            }).toMatchValues({
                // Verify merged results
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
                    expect.objectContaining({ id: '2' }),
                    expect.objectContaining({ id: '3' }),
                ]),
            })
        })

        it('shows all surveys when search term is empty', async () => {
            const surveys = [createTestSurvey('1', 'Test'), createTestSurvey('2', 'Another')]
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys,
                    surveysCount: 2,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('')
            }).toMatchValues({
                searchedSurveys: surveys,
            })
        })

        it('loads next page and maintains correct state', async () => {
            const page1 = [createTestSurvey('1', 'First'), createTestSurvey('2', 'Second')]
            const page2 = [createTestSurvey('3', 'Third'), createTestSurvey('4', 'Fourth')]

            // Load first page
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: page1,
                    surveysCount: 4,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
            }).toMatchValues({
                hasNextPage: true,
            })

            // Load second page
            await expectLogic(logic, () => {
                logic.actions.loadNextPageSuccess({
                    ...logic.values.data,
                    surveys: [...page1, ...page2],
                    surveysCount: 4,
                })
            }).toMatchValues({
                data: expect.objectContaining({
                    surveys: [...page1, ...page2],
                }),
                hasNextPage: false,
            })
        })
    })
})
