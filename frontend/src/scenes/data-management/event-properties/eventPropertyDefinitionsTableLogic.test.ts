import { initKeaTests } from '~/test/init'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { mockEventPropertyDefinitions } from '~/test/mocks'
import { useMocks } from '~/mocks/jest'
import { organizationLogic } from 'scenes/organizationLogic'
import { combineUrl, router } from 'kea-router'
import {
    EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
    eventPropertyDefinitionsTableLogic,
} from 'scenes/data-management/event-properties/eventPropertyDefinitionsTableLogic'
import { urls } from 'scenes/urls'

describe('eventPropertyDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof eventPropertyDefinitionsTableLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/property_definitions/': (req) => {
                    if (req.url.searchParams.get('order_ids_first')?.includes('uuid-5-foobar')) {
                        return [
                            200,
                            {
                                results: [
                                    mockEventPropertyDefinitions.find(({ id }) => id === 'uuid-5-foobar'),
                                    ...mockEventPropertyDefinitions.filter(({ id }) => id !== 'uuid-5-foobar'),
                                ],
                                count: 50,
                                previous: null,
                                next: null,
                            },
                        ]
                    }
                    if (req.url.searchParams.get('limit') === '50' && !req.url.searchParams.get('offset')) {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(0, 50),
                                count: 50,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/property_definitions${
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
                                results: mockEventPropertyDefinitions.slice(50, 56),
                                count: 6,
                                previous: `api/projects/${MOCK_TEAM_ID}/property_definitions${
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
            },
        })
        initKeaTests()
        await expectLogic(organizationLogic)
            .toFinishAllListeners()
            .toDispatchActions(['loadCurrentOrganizationSuccess'])
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = eventPropertyDefinitionsTableLogic({
            key: '1',
            syncWithUrl: true,
        })
        logic.mount()
    })

    describe('property definitions', () => {
        const startingUrl = `api/projects/${MOCK_TEAM_ID}/property_definitions${
            combineUrl('', {
                limit: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
                order_ids_first: [],
            }).search
        }`

        it('load event definitions on navigate and cache', async () => {
            const url = urls.eventPropertyDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadEventPropertyDefinitions',
                    'loadEventPropertyDefinitionsSuccess',
                ])
                .toMatchValues({
                    eventPropertyDefinitions: partial({
                        count: 50,
                        results: mockEventPropertyDefinitions.slice(0, 50),
                        previous: null,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
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
                logic.actions.loadEventPropertyDefinitions(startingUrl)
            }).toDispatchActions(['loadEventPropertyDefinitions', 'loadEventPropertyDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(1)
        })

        it('load property definitions on navigate and open specific definition', async () => {
            const startingDefinitionUrl = `api/projects/${MOCK_TEAM_ID}/property_definitions${
                combineUrl('', {
                    limit: EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
                    order_ids_first: ['uuid-5-foobar'],
                }).search
            }`

            const url = urls.eventPropertyDefinition('uuid-5-foobar')
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActionsInAnyOrder([
                    router.actionCreators.push(url),
                    'loadEventPropertyDefinitions',
                    'loadEventPropertyDefinitionsSuccess',
                    'setOpenedDefinition',
                ])
                .toMatchValues({
                    eventPropertyDefinitions: partial({
                        count: 50,
                        results: [
                            mockEventPropertyDefinitions.find(({ id }) => id === 'uuid-5-foobar'),
                            ...mockEventPropertyDefinitions.filter(({ id }) => id !== 'uuid-5-foobar'),
                        ],
                    }),
                    apiCache: partial({
                        [startingDefinitionUrl]: partial({
                            count: 50,
                        }),
                    }),
                })

            expect(api.get).toBeCalledTimes(1)
            expect(api.get).toBeCalledWith(startingDefinitionUrl)
        })

        it('pagination forwards and backwards', async () => {
            const url = urls.eventPropertyDefinitions()
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([
                    router.actionCreators.push(url),
                    'loadEventPropertyDefinitions',
                    'loadEventPropertyDefinitionsSuccess',
                ])
                .toMatchValues({
                    eventPropertyDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toBeCalledTimes(1)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadEventPropertyDefinitions(
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`
                )
            })
                .toDispatchActions(['loadEventPropertyDefinitions', 'loadEventPropertyDefinitionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    eventPropertyDefinitions: partial({
                        count: 6,
                        previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50`,
                        next: null,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadEventPropertyDefinitions(startingUrl)
            })
                .toDispatchActions(['loadEventPropertyDefinitions', 'loadEventPropertyDefinitionsSuccess'])
                .toMatchValues({
                    eventPropertyDefinitions: partial({
                        count: 50,
                        next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=50&offset=50`,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
        })
    })
})
