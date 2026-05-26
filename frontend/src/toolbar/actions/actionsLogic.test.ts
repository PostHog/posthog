import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { AccessControlLevel, ActionType } from '~/types'

const unsortedActions: ActionType[] = [
    {
        name: 'zoo',
        created_at: '',
        created_by: null,
        id: 1,
        pinned_at: null,
        user_access_level: AccessControlLevel.Editor,
    },
    {
        name: 'middle',
        created_at: '',
        created_by: null,
        id: 2,
        pinned_at: null,
        user_access_level: AccessControlLevel.Editor,
    },
    {
        name: 'begin',
        created_at: '',
        created_by: null,
        id: 3,
        pinned_at: null,
        user_access_level: AccessControlLevel.Editor,
    },
]
const apiJson = { results: unsortedActions }

const mockSuccess = (): Response =>
    ({
        ok: true,
        status: 200,
        json: () => Promise.resolve(apiJson),
    }) as any as Response

const mockFetch = jest.fn<Promise<Response>, [any?, any?]>(() => Promise.resolve(mockSuccess()))
global.fetch = mockFetch as any

describe('toolbar actionsLogic', () => {
    let logic: ReturnType<typeof actionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost', accessToken: 'test-token' }).mount()
        logic = actionsLogic()
        logic.mount()
        mockFetch.mockReset()
        mockFetch.mockImplementation(() => Promise.resolve(mockSuccess()))
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            sortedActions: [],
            searchTerm: '',
            allActions: [],
            actionCount: 0,
        })
    })

    it('can get actions', async () => {
        await expectLogic(logic, () => {
            logic.actions.getActions()
        })
            .delay(0)
            .toMatchValues({
                sortedActions: [
                    {
                        created_at: '',
                        created_by: null,
                        id: 3,
                        name: 'begin',
                        pinned_at: null,
                        user_access_level: AccessControlLevel.Editor,
                    },
                    {
                        created_at: '',
                        created_by: null,
                        id: 2,
                        name: 'middle',
                        pinned_at: null,
                        user_access_level: AccessControlLevel.Editor,
                    },
                    {
                        created_at: '',
                        created_by: null,
                        id: 1,
                        name: 'zoo',
                        pinned_at: null,
                        user_access_level: AccessControlLevel.Editor,
                    },
                ],
                actionCount: 3,
                allActions: apiJson.results,
            })
    })

    it('throws an error including the HTTP status on a non-2xx, non-403 response', async () => {
        mockFetch.mockImplementation(() =>
            Promise.resolve({
                ok: false,
                status: 500,
                text: () => Promise.resolve('Internal Server Error'),
                json: () => Promise.resolve({}),
            } as any as Response)
        )

        await expectLogic(logic, () => {
            logic.actions.getActions()
        })
            .delay(0)
            .toMatchValues({
                allActions: [],
            })

        expect(logic.values.allActionsLoading).toBe(false)
    })

    it('throws a shape-specific error when the response is OK but not a paginated array', async () => {
        mockFetch.mockImplementation(() =>
            Promise.resolve({
                ok: true,
                status: 200,
                text: () => Promise.resolve(''),
                json: () => Promise.resolve({ detail: 'something else' }),
            } as any as Response)
        )

        await expectLogic(logic, () => {
            logic.actions.getActions()
        })
            .delay(0)
            .toMatchValues({
                allActions: [],
            })

        expect(logic.values.allActionsLoading).toBe(false)
    })

    it('can filter the actions', async () => {
        await expectLogic(logic, () => {
            logic.actions.getActions()
            logic.actions.setSearchTerm('i')
        })
            .delay(0)
            .toMatchValues({
                sortedActions: [
                    {
                        created_at: '',
                        created_by: null,
                        id: 3,
                        name: 'begin',
                        pinned_at: null,
                        user_access_level: AccessControlLevel.Editor,
                    },
                    {
                        created_at: '',
                        created_by: null,
                        id: 2,
                        name: 'middle',
                        pinned_at: null,
                        user_access_level: AccessControlLevel.Editor,
                    },
                ],
            })
    })
})
