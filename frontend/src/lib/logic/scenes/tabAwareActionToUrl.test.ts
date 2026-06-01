import { actionToUrl as actionToUrlReal } from 'kea-router'

import { sceneLogic as sceneLogicReal } from 'scenes/sceneLogic'
import type { SceneTab } from 'scenes/sceneTypes'

import { tabAwareActionToUrl } from './tabAwareActionToUrl'

jest.mock('kea-router', () => {
    const actual = jest.requireActual('kea-router')
    return {
        ...actual,
        actionToUrl: jest.fn(() => jest.fn()),
    }
})

jest.mock('scenes/sceneLogic', () => ({
    sceneLogic: {
        isMounted: jest.fn(),
        values: { activeTabId: null as string | null, tabs: [] as SceneTab[] },
        actions: { setTabs: jest.fn() },
    },
}))

const actionToUrl = actionToUrlReal as unknown as jest.Mock
const sceneLogic = sceneLogicReal as unknown as {
    isMounted: jest.Mock
    values: { activeTabId: string | null; tabs: SceneTab[] }
    actions: { setTabs: jest.Mock }
}

const buildTab = (overrides: Partial<SceneTab>): SceneTab => ({
    id: 'A',
    pathname: '/sql',
    search: '',
    hash: '',
    title: 'A',
    active: false,
    iconType: 'blank',
    ...overrides,
})

const setupWrapped = (input: Record<string, any>, tabId: string): Record<string, (payload: any) => any> => {
    actionToUrl.mockClear()
    const fakeLogic = { pathString: 'test.logic', props: { tabId } } as any
    tabAwareActionToUrl(input)(fakeLogic)
    expect(actionToUrl).toHaveBeenCalledTimes(1)
    return actionToUrl.mock.calls[0][0]
}

describe('tabAwareActionToUrl', () => {
    beforeEach(() => {
        sceneLogic.isMounted.mockReturnValue(true)
        sceneLogic.values.activeTabId = null
        sceneLogic.values.tabs = []
        sceneLogic.actions.setTabs.mockClear()
    })

    describe('active tab', () => {
        it('returns the original action response so kea-router updates the URL', () => {
            sceneLogic.values.activeTabId = 'A'
            sceneLogic.values.tabs = [buildTab({ id: 'A', active: true })]

            const handler = jest.fn().mockReturnValue(['/sql', undefined, { q: 'SELECT 1' }, { replace: true }])
            const wrapped = setupWrapped({ syncUrlWithQuery: handler }, 'A')

            const response = wrapped.syncUrlWithQuery({})

            expect(handler).toHaveBeenCalledWith({})
            expect(response).toEqual(['/sql', undefined, { q: 'SELECT 1' }, { replace: true }])
            expect(sceneLogic.actions.setTabs).not.toHaveBeenCalled()
        })
    })

    describe('inactive tab', () => {
        it('writes pathname/search/hash from the action return onto this tab only', () => {
            sceneLogic.values.activeTabId = 'B'
            sceneLogic.values.tabs = [
                buildTab({ id: 'A', pathname: '/sql', hash: 'q=A_initial' }),
                buildTab({ id: 'B', pathname: '/sql', hash: 'q=B_initial', active: true }),
            ]

            const handler = jest.fn().mockReturnValue(['/sql', undefined, { q: 'A_edited' }, { replace: true }])
            const wrapped = setupWrapped({ syncUrlWithQuery: handler }, 'A')

            const response = wrapped.syncUrlWithQuery({})

            expect(response).toBeUndefined()
            expect(sceneLogic.actions.setTabs).toHaveBeenCalledTimes(1)
            const next = sceneLogic.actions.setTabs.mock.calls[0][0] as SceneTab[]
            const tabA = next.find((t) => t.id === 'A')!
            const tabB = next.find((t) => t.id === 'B')!
            expect(tabA.pathname).toBe('/sql')
            expect(tabA.hash).toBe('#q=A_edited')
            expect(tabB.hash).toBe('q=B_initial')
            expect(tabB.pathname).toBe('/sql')
        })

        it('does not call setTabs when the action returns falsy', () => {
            sceneLogic.values.activeTabId = 'B'
            sceneLogic.values.tabs = [buildTab({ id: 'A' }), buildTab({ id: 'B', active: true })]

            const handler = jest.fn().mockReturnValue(undefined)
            const wrapped = setupWrapped({ syncUrlWithQuery: handler }, 'A')

            expect(wrapped.syncUrlWithQuery({})).toBeUndefined()
            expect(sceneLogic.actions.setTabs).not.toHaveBeenCalled()
        })

        it('regression: does not read the active tab URL via router.values.location', () => {
            // Before the fix, the inactive branch read router.values.location (the
            // active tab's URL) and wrote it to a non-existent `url` field. After
            // the fix, the value comes from the action's own URL builder and
            // lands on pathname/hash. This test breaks if either regression returns.
            sceneLogic.values.activeTabId = 'B'
            sceneLogic.values.tabs = [
                buildTab({ id: 'A', pathname: '/sql', hash: 'q=A_initial' }),
                buildTab({ id: 'B', pathname: '/insights', hash: 'q=B_active', active: true }),
            ]

            const handler = jest.fn().mockReturnValue(['/sql', undefined, { q: 'A_edited' }, { replace: true }])
            const wrapped = setupWrapped({ syncUrlWithQuery: handler }, 'A')

            wrapped.syncUrlWithQuery({})

            const next = sceneLogic.actions.setTabs.mock.calls[0][0] as SceneTab[]
            const tabA = next.find((t) => t.id === 'A')!
            expect(tabA.pathname).not.toBe('/insights')
            expect(tabA.hash).not.toContain('B_active')
            expect((tabA as any).url).toBeUndefined()
        })
    })

    it('passes through unmodified when sceneLogic is not mounted', () => {
        sceneLogic.isMounted.mockReturnValue(false)

        const handler = jest.fn().mockReturnValue(['/sql', undefined, { q: 'X' }])
        const wrapped = setupWrapped({ syncUrlWithQuery: handler }, 'A')

        const response = wrapped.syncUrlWithQuery({})

        expect(handler).toHaveBeenCalledWith({})
        expect(response).toEqual(['/sql', undefined, { q: 'X' }])
        expect(sceneLogic.actions.setTabs).not.toHaveBeenCalled()
    })
})
