import { MOCK_GROUP_TYPES, MOCK_TEAM_ID, api } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'

import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    PropertyDefinitionWithQueryUsage,
    QUERY_USAGE_COLUMN_KEY,
    propertyDefinitionsTableLogic,
    queryUsageOrderingFromSorting,
} from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventPropertyDefinitions } from '~/test/mocks'

describe('propertyDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof propertyDefinitionsTableLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/property_definitions/': ({ request }) => {
                    const url = new URL(request.url)
                    if (url.searchParams.get('limit') === '50' && !url.searchParams.get('offset')) {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(0, 50),
                                count: 50,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/property_definitions${
                                    combineUrl(url.pathname, {
                                        ...url.searchParams,
                                        limit: 50,
                                        offset: 50,
                                    }).search
                                }`,
                            },
                        ]
                    }
                    if (url.searchParams.get('limit') === '50' && url.searchParams.get('offset') === '50') {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(50, 56),
                                count: 6,
                                previous: `api/projects/${MOCK_TEAM_ID}/property_definitions${
                                    combineUrl(url.pathname, {
                                        ...url.searchParams,
                                        limit: 50,
                                        offset: undefined,
                                    }).search
                                }`,
                                next: null,
                            },
                        ]
                    }
                },
                'api/projects/:team/groups_types': MOCK_GROUP_TYPES,
            },
        })
        initKeaTests()
        await expectLogic(organizationLogic)
            .toFinishAllListeners()
            .toDispatchActions(['loadCurrentOrganizationSuccess'])
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = propertyDefinitionsTableLogic({
            key: '1',
            syncWithUrl: true,
        })
        logic.mount()
    })

    describe('request timing', () => {
        const listRequests = (): unknown[][] =>
            api.get.mock.calls.filter(([url]) => String(url).includes('/property_definitions'))

        beforeEach(() => {
            logic.unmount()
            jest.useFakeTimers()
            api.get.mockClear()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each<[string, Record<string, string>]>([
            ['a bare URL', {}],
            ['a search in the URL', { property: 'checkout' }],
        ])('sends one request at once when the page opens on %s', async (_, searchParams) => {
            router.actions.push(urls.propertyDefinitions(), searchParams)
            logic = propertyDefinitionsTableLogic({ key: '1', syncWithUrl: true })
            logic.mount()

            expect(listRequests()).toHaveLength(1)

            await jest.advanceTimersByTimeAsync(1000)
            expect(listRequests()).toHaveLength(1)
        })

        it.each([
            ['the list has results', false],
            ['the list is empty', true],
        ])('waits for typing in the search box to pause, then sends one request when %s', async (_, emptyList) => {
            router.actions.push(urls.propertyDefinitions())
            logic = propertyDefinitionsTableLogic({ key: '1', syncWithUrl: true })
            logic.mount()
            await jest.advanceTimersByTimeAsync(1000)
            if (emptyList) {
                logic.actions.loadPropertyDefinitionsSuccess({ count: 0, results: [] })
            }
            api.get.mockClear()

            logic.actions.setFilters({ property: 'chec' })
            logic.actions.setFilters({ property: 'checkout' })
            await jest.advanceTimersByTimeAsync(500 - 1)
            expect(listRequests()).toHaveLength(0)

            await jest.advanceTimersByTimeAsync(1)
            expect(listRequests()).toEqual([[expect.stringContaining('search=checkout')]])
        })
    })

    describe('property definitions', () => {
        const startingUrl = `api/projects/${MOCK_TEAM_ID}/property_definitions${
            combineUrl('', {
                limit: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
            }).search
        }`

        it('load event definitions on navigate and cache', async () => {
            const url = urls.propertyDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadPropertyDefinitions',
                    'loadPropertyDefinitionsSuccess',
                ])
                .toMatchValues({
                    propertyDefinitions: partial({
                        count: 50,
                        results: mockEventPropertyDefinitions.slice(0, 50),
                        previous: null,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
                    }),
                })

            expect(api.get).toHaveBeenCalledTimes(1)
            expect(api.get).toHaveBeenCalledWith(startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(startingUrl)
            }).toDispatchActions(['loadPropertyDefinitions', 'loadPropertyDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toHaveBeenCalledTimes(1)
        })

        it.each([
            {
                outcome: 'succeeded',
                error: null,
                action: 'loadPropertyDefinitionsSuccess',
                event: 'event property definitions page load succeeded',
                expectedProperties: { num_results: 50 },
            },
            {
                outcome: 'failed',
                error: 'request failed',
                action: 'loadPropertyDefinitionsFailure',
                event: 'event property definitions page load failed',
                expectedProperties: { error: 'There was an unknown error fetching property definitions.' },
            },
        ])(
            'captures when loading property definitions $outcome',
            async ({ error, action, event, expectedProperties }) => {
                const capture = jest.spyOn(posthog, 'capture').mockImplementation()
                try {
                    if (error) {
                        api.get.mockRejectedValueOnce(error)
                    }
                    await expectLogic(logic, () =>
                        logic.actions.loadPropertyDefinitions(startingUrl)
                    ).toDispatchActions([action])

                    expect(capture).toHaveBeenCalledWith(
                        event,
                        expect.objectContaining({ load_time: expect.any(Number), ...expectedProperties })
                    )
                } finally {
                    capture.mockRestore()
                }
            }
        )

        it('pagination forwards and backwards', async () => {
            const url = urls.propertyDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadPropertyDefinitions',
                    'loadPropertyDefinitionsSuccess',
                ])
                .toMatchValues({
                    propertyDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(1)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`
                )
            })
                .toDispatchActions(['loadPropertyDefinitions', 'loadPropertyDefinitionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    propertyDefinitions: partial({
                        count: 6,
                        previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50`,
                        next: null,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(2)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(startingUrl)
            })
                .toDispatchActions(['loadPropertyDefinitions', 'loadPropertyDefinitionsSuccess'])
                .toMatchValues({
                    propertyDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(2)
        })
    })

    describe('query usage', () => {
        const listRequestParams = (): URLSearchParams[] =>
            api.get.mock.calls
                .filter(([url]) => String(url).includes('/property_definitions'))
                .map(([url]) => new URLSearchParams(String(url).split('?')[1]))

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/property_definitions/': () => [
                        200,
                        { count: 1, results: mockEventPropertyDefinitions.slice(0, 1), next: null, previous: null },
                    ],
                },
            })
        })

        const setUsageFlag = (enabled: boolean): void => {
            featureFlagLogic.actions.setFeatureFlags(
                [FEATURE_FLAGS.DEFINITION_USAGE_SECTION],
                enabled ? { [FEATURE_FLAGS.DEFINITION_USAGE_SECTION]: true } : {}
            )
        }

        it.each([
            ['most queried with the flag on', true, '-query_usage', '-query_usage', 'true'],
            ['least queried with the flag on', true, 'query_usage', 'query_usage', 'true'],
            ['an unknown ordering with the flag on', true, 'name', null, 'true'],
            ['most queried with the flag off', false, '-query_usage', null, null],
        ])(
            'requests the order from the URL for %s',
            async (_, flagEnabled, urlOrdering, expectedOrdering, expectedIncludeUsage) => {
                setUsageFlag(flagEnabled)
                api.get.mockClear()

                router.actions.push(urls.propertyDefinitions(), { ordering: urlOrdering })
                await expectLogic(logic).toDispatchActions(['loadPropertyDefinitionsSuccess']).toFinishAllListeners()

                const [params] = listRequestParams()
                expect(params.get('ordering')).toEqual(expectedOrdering)
                expect(params.get('include_query_usage')).toEqual(expectedIncludeUsage)
            }
        )

        it('writes a column sort to the URL and clears it again', async () => {
            setUsageFlag(true)
            router.actions.push(urls.propertyDefinitions())
            await expectLogic(logic).toDispatchActions(['loadPropertyDefinitionsSuccess']).toFinishAllListeners()

            logic.actions.setFilters(
                { ordering: queryUsageOrderingFromSorting({ columnKey: QUERY_USAGE_COLUMN_KEY, order: -1 }) },
                false
            )
            await expectLogic(logic).toDispatchActions(['loadPropertyDefinitionsSuccess']).toFinishAllListeners()

            expect(router.values.searchParams.ordering).toEqual('-query_usage')
            expect(logic.values.queryUsageSorting).toEqual({ columnKey: QUERY_USAGE_COLUMN_KEY, order: -1 })
            expect(listRequestParams().at(-1)?.get('ordering')).toEqual('-query_usage')

            logic.actions.setFilters({ ordering: queryUsageOrderingFromSorting(null) }, false)
            await expectLogic(logic).toDispatchActions(['loadPropertyDefinitionsSuccess']).toFinishAllListeners()

            expect(router.values.searchParams.ordering).toBeUndefined()
            expect(listRequestParams().at(-1)?.get('ordering')).toBeNull()
        })

        it.each([
            [
                'the project has too many properties to sort',
                { code: 'too_many_properties_to_order_by_usage', detail: 'Too many properties to sort.' },
                'Too many properties to sort.',
            ],
            ['the request failed for another reason', { code: 'error', detail: 'Server error' }, null],
        ])('shows a sort error only when %s', async (_, errorObject, expectedError) => {
            setUsageFlag(true)

            logic.actions.loadPropertyDefinitionsFailure('Request failed', errorObject)

            expect(logic.values.usageSortError).toEqual(expectedError)
        })

        it('reads the coverage of a young project from the list response', () => {
            logic.actions.loadPropertyDefinitionsSuccess({
                count: 1,
                results: [{ id: 'a', name: 'plan', query_usage_30_day: 4 } as PropertyDefinitionWithQueryUsage],
                query_usage: { computed_at: '2026-11-12T10:00:00Z', tracking_since: '2026-11-09T14:00:00Z' },
            })

            expect(logic.values.queryUsageCoverageDays).toEqual(3)
        })
    })
})
