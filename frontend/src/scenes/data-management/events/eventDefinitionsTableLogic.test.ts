import { initKeaTests } from '~/test/init'
import {
    EVENT_DEFINITIONS_PER_PAGE,
    eventDefinitionsTableLogic,
    PROPERTY_DEFINITIONS_PER_EVENT,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { mockEvent, mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { useMocks } from '~/mocks/jest'
import { organizationLogic } from 'scenes/organizationLogic'
import { combineUrl, router } from 'kea-router'
import { keyMappingKeys } from 'lib/components/PropertyKeyInfo'
import { urls } from 'scenes/urls'

describe('eventDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof eventDefinitionsTableLogic.build>
    const startingUrl = `api/projects/${MOCK_TEAM_ID}/event_definitions${
        combineUrl('', {
            limit: EVENT_DEFINITIONS_PER_PAGE,
        }).search
    }`

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': (req) => {
                    if (req.url.searchParams.get('limit') === '50' && !req.url.searchParams.get('offset')) {
                        return [
                            200,
                            {
                                results: mockEventDefinitions.slice(0, 50),
                                count: 50,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/event_definitions${
                                    combineUrl(req.url.pathname, {
                                        ...req.url.searchParams,
                                        limit: 50,
                                        offset: 50,
                                    }).search
                                }`,
                            },
                        ]
                    }
                    if (req.url.searchParams.get('limit') === '50' && req.url.searchParams.get('offset') === '50') {
                        return [
                            200,
                            {
                                results: mockEventDefinitions.slice(50, 56),
                                count: 6,
                                previous: `api/projects/${MOCK_TEAM_ID}/event_definitions${
                                    combineUrl(req.url.pathname, {
                                        ...req.url.searchParams,
                                        limit: 50,
                                        offset: undefined,
                                    }).search
                                }`,
                                next: null,
                            },
                        ]
                    }
                },
                '/api/projects/:team/property_definitions': (req) => {
                    if (req.url.searchParams.get('limit') === '5' && !req.url.searchParams.get('offset')) {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(0, 5),
                                count: 5,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/property_definitions${
                                    combineUrl(req.url.pathname, {
                                        ...req.url.searchParams,
                                        limit: 5,
                                        offset: 5,
                                    }).search
                                }`,
                            },
                        ]
                    }
                    if (req.url.searchParams.get('limit') === '5' && req.url.searchParams.get('offset') === '5') {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(5, 8),
                                count: 3,
                                previous: `api/projects/${MOCK_TEAM_ID}/property_definitions${
                                    combineUrl(req.url.pathname, {
                                        ...req.url.searchParams,
                                        limit: 5,
                                        offset: undefined,
                                    }).search
                                }`,
                                next: null,
                            },
                        ]
                    }
                },
                '/api/projects/:team/events': (req) => {
                    if (
                        req.url.searchParams.get('limit') === '1' &&
                        req.url.searchParams.get('event') === 'event_with_example'
                    ) {
                        return [
                            200,
                            {
                                results: [
                                    { ...mockEvent, properties: { ...mockEvent.properties, $browser: 'Chrome' } },
                                ],
                                next: null,
                            },
                        ]
                    }
                    if (req.url.searchParams.get('limit') === '1') {
                        return [200, { results: [mockEvent], next: null }]
                    }
                },
            },
        })
        initKeaTests()
        await expectLogic(organizationLogic)
            .toFinishAllListeners()
            .toDispatchActions(['loadCurrentOrganizationSuccess'])
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = eventDefinitionsTableLogic({
            key: '1',
            syncWithUrl: true,
        })
        logic.mount()
    })

    describe('event definitions', () => {
        it('load event definitions on navigate and cache', async () => {
            const url = urls.eventDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadEventDefinitions',
                    'loadEventDefinitionsSuccess',
                ])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 50,
                        results: mockEventDefinitions.slice(0, 50),
                        previous: null,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
                    }),
                    apiCache: partial({
                        [startingUrl]: partial({
                            count: 50,
                        }),
                    }),
                })

            expect(api.get).toBeCalledTimes(1)
            expect(api.get).toBeCalledWith(startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(startingUrl)
            }).toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(1)
        })

        it('pagination forwards and backwards', async () => {
            const url = urls.eventDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadEventDefinitions',
                    'loadEventDefinitionsSuccess',
                ])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toBeCalledTimes(1)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`)
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 6,
                        previous: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`,
                        next: null,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(startingUrl)
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
        })
    })

    describe('property definitions', () => {
        const eventDefinition = mockEventDefinitions[0]
        const propertiesStartingUrl = `api/projects/${MOCK_TEAM_ID}/property_definitions${
            combineUrl('', {
                limit: PROPERTY_DEFINITIONS_PER_EVENT,
                event_names: ['event1'],
                excluded_properties: keyMappingKeys,
                is_event_property: true,
            }).search
        }`
        const url = urls.eventDefinitions()

        beforeEach(() => {
            router.actions.push(url)
        })

        it('load property definitions and cache', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition)
            })
                .toDispatchActionsInAnyOrder([
                    router.actionCreators.push(url),
                    'loadEventDefinitions',
                    'loadEventDefinitionsSuccess',
                    'loadPropertiesForEvent',
                    'loadPropertiesForEventSuccess',
                ])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            results: mockEventPropertyDefinitions.slice(0, 5),
                            previous: null,
                            current: propertiesStartingUrl,
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                    apiCache: partial({
                        [startingUrl]: partial({
                            count: 50,
                        }),
                        [propertiesStartingUrl]: partial({
                            count: 5,
                        }),
                        [`api/projects/${MOCK_TEAM_ID}/events?event=event1&limit=1&orderBy=%5B%22-timestamp%22%5D`]:
                            partial(mockEvent.properties),
                    }),
                })

            expect(api.get).toBeCalledTimes(3)
            expect(api.get).toHaveBeenNthCalledWith(1, propertiesStartingUrl)
            expect(api.get).toHaveBeenNthCalledWith(
                2,
                `api/projects/${MOCK_TEAM_ID}/events?event=event1&limit=1&orderBy=%5B%22-timestamp%22%5D`
            )
            expect(api.get).toHaveBeenNthCalledWith(3, startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition, startingUrl)
            }).toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(3)
        })

        it('inject example', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent({ ...eventDefinition, name: 'event_with_example' })
            })
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadPropertiesForEvent',
                    'loadPropertiesForEventSuccess',
                ])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            previous: null,
                            results: mockEventPropertyDefinitions.slice(0, 5).map((prop) =>
                                prop.name === '$browser'
                                    ? {
                                          ...prop,
                                          example: 'Chrome',
                                      }
                                    : prop
                            ),
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
        })

        it('pagination forwards and backwards', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition)
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(
                    eventDefinition,
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`
                )
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 3,
                            previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
                            next: null,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(3)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition, propertiesStartingUrl)
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(3)
        })
    })
})
