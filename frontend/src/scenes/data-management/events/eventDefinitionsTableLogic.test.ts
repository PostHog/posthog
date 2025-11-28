import { MOCK_TEAM_ID, api } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { EVENT_DEFINITIONS_PER_PAGE, PROPERTY_DEFINITIONS_PER_EVENT } from 'lib/constants'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEvent, mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { EventDefinitionType } from '~/types'

describe('eventDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof eventDefinitionsTableLogic.build>
    const startingUrl = `api/projects/${MOCK_TEAM_ID}/event_definitions${
        combineUrl('', {
            limit: EVENT_DEFINITIONS_PER_PAGE,
            search: '',
            ordering: 'event',
            event_type: EventDefinitionType.Event,
        }).search
    }`

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': (req) => {
                    const limit = req.url.searchParams.get('limit')
                    const offset = req.url.searchParams.get('offset')

                    if (limit === '50' && !offset) {
                        return [
                            200,
                            {
                                results: mockEventDefinitions.slice(0, 50),
                                count: 50,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/event_definitions${
                                    combineUrl(req.url.pathname, {
                                        limit: 50,
                                        offset: 50,
                                        event_type: EventDefinitionType.Event,
                                    }).search
                                }`,
                            },
                        ]
                    }
                    if (limit === '50' && offset === '50') {
                        return [
                            200,
                            {
                                results: mockEventDefinitions.slice(50, 56),
                                count: 6,
                                previous: `api/projects/${MOCK_TEAM_ID}/event_definitions${
                                    combineUrl(req.url.pathname, {
                                        limit: 50,
                                        event_type: EventDefinitionType.Event,
                                    }).search
                                }`,
                                next: null,
                            },
                        ]
                    }
                },
                '/api/projects/:team/property_definitions': (req) => {
                    const limit = req.url.searchParams.get('limit')
                    const offset = req.url.searchParams.get('offset')

                    if (limit === '5' && !offset) {
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
                    if (limit === '5' && offset === '5') {
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
                '/api/environments/:team_id/events': (req) => {
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
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50&event_type=event`,
                    }),
                })

            // Check cache directly
            expect(logic.cache.apiCache).toMatchObject({
                [startingUrl]: expect.objectContaining({
                    count: 50,
                }),
            })

            expect(api.get).toHaveBeenCalledTimes(1)
            expect(api.get).toHaveBeenCalledWith(startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(startingUrl)
            }).toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toHaveBeenCalledTimes(1)
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
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50&event_type=event`,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(1)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(
                    `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50&event_type=event`
                )
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 6,
                        previous: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&event_type=event`,
                        next: null,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(2)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(startingUrl)
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50&event_type=event`,
                    }),
                })
            expect(api.get).toHaveBeenCalledTimes(2)
        })
    })

    describe('property definitions', () => {
        const eventDefinition = mockEventDefinitions[0]
        const propertiesStartingUrl = `api/projects/${MOCK_TEAM_ID}/property_definitions${
            combineUrl('', {
                limit: PROPERTY_DEFINITIONS_PER_EVENT,
                event_names: ['event1'],
                exclude_core_properties: true,
                filter_by_event_names: true,
                is_feature_flag: false,
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
                })

            // Check cache directly
            expect(logic.cache.apiCache).toMatchObject({
                [startingUrl]: expect.objectContaining({
                    count: 50,
                }),
                [propertiesStartingUrl]: expect.objectContaining({
                    count: 5,
                }),
                [`api/environments/${MOCK_TEAM_ID}/events?event=event1&limit=1`]: expect.objectContaining(
                    mockEvent.properties
                ),
            })

            expect(api.get).toHaveBeenCalledTimes(3)
            expect(api.get).toHaveBeenNthCalledWith(1, propertiesStartingUrl)
            expect(api.get).toHaveBeenNthCalledWith(2, `api/environments/${MOCK_TEAM_ID}/events?event=event1&limit=1`)
            expect(api.get).toHaveBeenNthCalledWith(3, startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition, startingUrl)
            }).toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])

            // Doesn't call api.get again
            expect(api.get).toHaveBeenCalledTimes(3)
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
            expect(api.get).toHaveBeenCalledTimes(2)
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
            expect(api.get).toHaveBeenCalledTimes(3)
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
            expect(api.get).toHaveBeenCalledTimes(3)
        })
    })
})
