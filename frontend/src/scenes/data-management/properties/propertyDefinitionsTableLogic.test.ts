import { initKeaTests } from '~/test/init'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { mockEventPropertyDefinitions } from '~/test/mocks'
import { useMocks } from '~/mocks/jest'
import { organizationLogic } from 'scenes/organizationLogic'
import { combineUrl, router } from 'kea-router'
import {
    EVENT_PROPERTY_DEFINITIONS_PER_PAGE,
    propertyDefinitionsTableLogic,
} from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { urls } from 'scenes/urls'

describe('propertyDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof propertyDefinitionsTableLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/property_definitions/': (req) => {
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
        logic = propertyDefinitionsTableLogic({
            key: '1',
            syncWithUrl: true,
        })
        logic.mount()
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

            expect(api.get).toBeCalledTimes(1)
            expect(api.get).toBeCalledWith(startingUrl)

            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(startingUrl)
            }).toDispatchActions(['loadPropertyDefinitions', 'loadPropertyDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(1)
        })

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
            expect(api.get).toBeCalledTimes(1)
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
            expect(api.get).toBeCalledTimes(2)
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
            expect(api.get).toBeCalledTimes(2)
        })
    })
})
