import { MOCK_GROUP_TYPES, MOCK_TEAM_ID, api } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'

import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventPropertyDefinitions } from '~/test/mocks'
import { PropertyDefinition, PropertyDefinitionType } from '~/types'

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
        const definitions = [
            { id: 'a', name: 'plan', type: PropertyDefinitionType.Event },
            { id: 'b', name: '$virt', type: PropertyDefinitionType.Event, virtual: true },
            { id: 'c', name: 'industry', type: PropertyDefinitionType.Group, group_type_index: 0 },
            { id: 'd', name: 'industry', type: PropertyDefinitionType.Group },
            { id: 'e', name: 'email', type: PropertyDefinitionType.Person },
        ] as PropertyDefinition[]
        let requestedProperties: unknown[] | null

        beforeEach(() => {
            requestedProperties = null
            useMocks({
                post: {
                    '/api/projects/:team/property_definitions/usage_metrics/': async ({ request }) => {
                        const { properties } = (await request.json()) as { properties: Record<string, unknown>[] }
                        requestedProperties = properties
                        return [
                            200,
                            {
                                results: properties.map((entry, index) => ({
                                    ...entry,
                                    group_type_index: entry.group_type_index ?? null,
                                    query_usage_30_day: (index + 1) * 10,
                                })),
                            },
                        ]
                    },
                },
            })
        })

        it.each([
            [
                'on',
                { a: 10, c: 20, e: 30 },
                [
                    { type: 'event', name: 'plan' },
                    { type: 'group', name: 'industry', group_type_index: 0 },
                    { type: 'person', name: 'email' },
                ],
            ],
            ['off', null, null],
        ])(
            'loads counts for the visible page by definition id when the flag is %s',
            async (flag, expectedUsage, expectedRequest) => {
                featureFlagLogic.actions.setFeatureFlags(
                    [FEATURE_FLAGS.DEFINITION_USAGE_SECTION],
                    flag === 'on' ? { [FEATURE_FLAGS.DEFINITION_USAGE_SECTION]: true } : {}
                )

                logic.actions.loadPropertyDefinitionsSuccess({ count: definitions.length, results: definitions })
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.queryUsage).toEqual(expectedUsage)
                expect(requestedProperties).toEqual(expectedRequest)
            }
        )
    })
})
