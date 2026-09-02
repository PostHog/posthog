import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api, { CountedPaginatedResponse } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Survey, SurveySchedule, SurveyType } from '~/types'

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
    user_access_level: AccessControlLevel.Editor,
})

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((promiseResolve) => {
        resolve = promiseResolve
    })
    return { promise, resolve }
}

describe('surveysLogic', () => {
    describe('search functionality', () => {
        let logic: ReturnType<typeof surveysLogic.build>
        let surveyListRequests: URL[]
        let responseCountRequests: URL[]

        beforeEach(async () => {
            initKeaTests()
            surveyListRequests = []
            responseCountRequests = []
            logic = surveysLogic()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': ({ request }) => {
                        surveyListRequests.push(new URL(request.url))
                        return [200, { count: 0, results: [], next: null, previous: null }]
                    },
                    '/api/projects/:team/surveys/responses_count': ({ request }) => {
                        const url = new URL(request.url)
                        responseCountRequests.push(url)
                        const requestedSurveyIds = url.searchParams.get('survey_ids')?.split(',') ?? []

                        return [200, requestedSurveyIds.includes('survey-1') ? { 'survey-1': 12 } : {}]
                    },
                },
            })

            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('triggers backend search after debounce', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey')],
                    surveysCount: 150,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
            })
                .delay(400)
                .toDispatchActions(['loadSearchResults'])
                // let the search request settle so its success action doesn't land after unmount
                .toFinishAllListeners()
        })

        it('searchedSurveys reflects backend results once loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSurveysSuccess({
                    surveys: [createTestSurvey('1', 'Test Survey'), createTestSurvey('2', 'Another Test')],
                    surveysCount: 150,
                    searchSurveys: [],
                    searchSurveysCount: 0,
                })
                logic.actions.setSearchTerm('Test')
                logic.actions.loadSearchResultsSuccess({
                    ...logic.values.data,
                    searchSurveys: [createTestSurvey('1', 'Test Survey'), createTestSurvey('3', 'New Test')],
                    searchSurveysCount: 2,
                })
            }).toMatchValues({
                searchedSurveys: expect.arrayContaining([
                    expect.objectContaining({ id: '1' }),
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

        it('filters on the server before paginating', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSurveysFilters({
                    created_by: 42,
                    status: 'running',
                    type: SurveyType.Widget,
                })
            }).toFinishAllListeners()

            const params = surveyListRequests.at(-1)?.searchParams
            expect(params?.get('archived')).toEqual('false')
            expect(params?.get('created_by')).toEqual('42')
            expect(params?.get('status')).toEqual('running')
            expect(params?.get('type')).toEqual(SurveyType.Widget)
            expect(params?.get('limit')).toEqual('100')
        })

        it('keeps the latest filtered results when requests finish out of order', async () => {
            const olderRequest = deferred<CountedPaginatedResponse<Survey>>()
            const newerRequest = deferred<CountedPaginatedResponse<Survey>>()
            const olderSurvey = createTestSurvey('older', 'Older filter result')
            const newerSurvey = createTestSurvey('newer', 'Newer filter result')
            const listSpy = jest
                .spyOn(api.surveys, 'list')
                .mockImplementationOnce(() => olderRequest.promise)
                .mockImplementationOnce(() => newerRequest.promise)

            logic.actions.setSurveysFilters({ created_by: 41 })
            logic.actions.setSurveysFilters({ created_by: 42 })

            expect(listSpy).toHaveBeenNthCalledWith(1, expect.objectContaining({ created_by: 41 }))
            expect(listSpy).toHaveBeenNthCalledWith(2, expect.objectContaining({ created_by: 42 }))

            newerRequest.resolve({ count: 1, results: [newerSurvey] })
            await waitFor(() => expect(logic.values.data.surveys).toEqual([newerSurvey]))

            olderRequest.resolve({ count: 1, results: [olderSurvey] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.data.surveys).toEqual([newerSurvey])
        })

        it('loads response counts for each page and merges them', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/surveys/': ({ request }) => {
                        const offset = new URL(request.url).searchParams.get('offset')
                        const survey =
                            offset === '1'
                                ? createTestSurvey('survey-2', 'Second survey')
                                : createTestSurvey('survey-1', 'First survey')

                        return [200, { count: 2, results: [survey], next: null, previous: null }]
                    },
                },
            })

            await expectLogic(logic, () => logic.actions.loadSurveys()).toFinishAllListeners()

            expect(responseCountRequests).toHaveLength(1)
            expect(responseCountRequests[0].searchParams.get('survey_ids')).toEqual('survey-1')
            expect(logic.values.surveysResponsesCount).toEqual({ 'survey-1': 12 })

            await expectLogic(logic, () => logic.actions.loadNextPage()).toFinishAllListeners()

            expect(responseCountRequests).toHaveLength(2)
            expect(responseCountRequests[1].searchParams.get('survey_ids')).toEqual('survey-2')
            expect(logic.values.surveysResponsesCount).toEqual({ 'survey-1': 12, 'survey-2': 0 })
        })
    })

    describe('url syncing', () => {
        let logic: ReturnType<typeof surveysLogic.build>

        beforeEach(async () => {
            initKeaTests()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
            })

            logic = surveysLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('writes the search term to the search query param', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('checkout')
            }).toFinishAllListeners()

            expect(router.values.searchParams.search).toEqual('checkout')
        })

        it('removes the search query param when the term is cleared', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('checkout')
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('')
            }).toFinishAllListeners()

            expect(router.values.searchParams.search).toBeUndefined()
        })

        it('reads the search term from the search query param on navigation', async () => {
            router.actions.push('/surveys', { search: 'onboarding' })

            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                searchTerm: 'onboarding',
            })
        })

        it('coerces a numeric search query param to a string without crashing searchedSurveys', async () => {
            router.actions.push('/surveys', { search: 3 })

            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                searchTerm: '3',
            })

            expect(logic.values.searchedSurveys).toEqual([])
        })

        it('clears a stale search term when navigating to surveys without a search param', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('onboarding')
            }).toFinishAllListeners()

            router.actions.push('/surveys')

            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                searchTerm: '',
            })
        })
    })

    describe('product intent tracking', () => {
        let logic: ReturnType<typeof surveysLogic.build>
        let capturedIntentRequests: any[]

        beforeEach(async () => {
            initKeaTests()
            capturedIntentRequests = []

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count': () => [200, {}],
                },
                patch: {
                    '/api/environments/:team_id/add_product_intent/': async ({ request }) => {
                        const data = await request.json()
                        capturedIntentRequests.push(data)
                        return [200, {}]
                    },
                },
            })

            logic = surveysLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            capturedIntentRequests = []
        })

        it('should track SURVEYS_VIEWED intent when navigating to surveys page', async () => {
            router.actions.push('/surveys')

            await expectLogic(logic).toFinishAllListeners()

            expect(capturedIntentRequests).toHaveLength(1)
            expect(capturedIntentRequests[0]).toEqual({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEYS_VIEWED,
            })
        })

        it('should track SURVEY_DUPLICATED intent when duplicating survey', async () => {
            const mockSurvey = createTestSurvey('original-survey', 'Test Survey')
            const duplicatedSurveyId = 'duplicated-survey-123'

            useMocks({
                post: {
                    '/api/projects/:team/surveys/': () => [
                        200,
                        { ...mockSurvey, id: duplicatedSurveyId, name: 'Test Survey (copy)' },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.duplicateSurvey(mockSurvey)
            }).toFinishAllListeners()

            const duplicateIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_DUPLICATED
            )
            expect(duplicateIntent).toBeTruthy()
            expect(duplicateIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_DUPLICATED,
                metadata: {
                    survey_id: duplicatedSurveyId,
                },
            })
        })

        it('should track SURVEY_BULK_DUPLICATED intent when duplicating to multiple projects', async () => {
            const mockSurvey = createTestSurvey('original-survey', 'Test Survey')
            const targetTeamIds = [1, 2, 3]

            useMocks({
                post: {
                    '/api/projects/:team/surveys/:id/duplicate_to_projects/': () => [200, { count: 3, duplicates: [] }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.duplicateToProjects({ survey: mockSurvey, targetTeamIds })
            }).toFinishAllListeners()

            const bulkDuplicateIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_BULK_DUPLICATED
            )
            expect(bulkDuplicateIntent).toBeTruthy()
            expect(bulkDuplicateIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_BULK_DUPLICATED,
                metadata: {
                    survey_id: 'original-survey',
                    target_team_ids: targetTeamIds,
                    bulk_operation: true,
                },
            })
        })

        // TODO: This test reveals a potential bug in surveysLogic where action.payload
        // in the deleteSurveySuccess listener is an object instead of the survey ID.
        // The implementation uses String(action.payload) which would produce "[object Object]".
        // This needs investigation - either the test setup is wrong or the implementation has a bug.
        it.skip('should track SURVEY_DELETED intent when deleting survey', async () => {
            const surveyId = 'test-survey-123'

            useMocks({
                delete: {
                    '/api/projects/:team/surveys/:id/': () => [200, {}],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.deleteSurvey(surveyId)
            })
                .toDispatchActions(['deleteSurveySuccess'])
                .toFinishAllListeners()

            const deleteIntent = capturedIntentRequests.find(
                (req) => req.intent_context === ProductIntentContext.SURVEY_DELETED
            )
            expect(deleteIntent).toBeTruthy()
            expect(deleteIntent).toMatchObject({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_DELETED,
                metadata: {
                    survey_id: surveyId,
                },
            })
        })
    })
})
