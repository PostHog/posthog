import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { SearchItem } from 'lib/components/Search/searchLogic'

import { initKeaTests } from '~/test/init'

import { osWindowsLogic } from '../windows/osWindowsLogic'
import { osSpotlightLogic } from './osSpotlightLogic'

const HOME = `/project/${MOCK_TEAM_ID}/home`

function result(href: string): SearchItem {
    return { id: href, name: href, category: 'insight', href } as SearchItem
}

describe('osSpotlightLogic', () => {
    let windows: ReturnType<typeof osWindowsLogic.build>
    let logic: ReturnType<typeof osSpotlightLogic.build>

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        initKeaTests(true)
        router.actions.push(HOME)
        windows = osWindowsLogic()
        windows.mount()
        logic = osSpotlightLogic()
        logic.mount()
        logic.actions.openSpotlight()
    })

    afterEach(() => {
        logic.unmount()
        windows.unmount()
        jest.restoreAllMocks()
    })

    test.each([
        [
            'an entity opens in a window',
            result('/insights/abc'),
            false,
            [HOME, `/project/${MOCK_TEAM_ID}/insights/abc`],
        ],
        ['an app that already has a window comes to the front', result('/home'), false, [HOME]],
        ['a Cmd+Enter opens another window', result('/home'), true, [HOME, HOME]],
        ['a placeholder result does nothing', result('#'), false, [HOME]],
        ['a script href does nothing', result('javascript:alert(1)'), false, [HOME]],
    ])('%s', (_description, item, newWindow, expectedPaths) => {
        logic.actions.selectResult(item, newWindow)

        expect(windows.values.windows.map((w) => w.path)).toEqual(expectedPaths)
        expect(windows.values.focusedWindow?.path).toBe(expectedPaths[expectedPaths.length - 1])
        expect(commandLogic.values.isCommandOpen).toBe(false)
    })

    it('opens an external result in a browser tab', () => {
        const open = jest.spyOn(window, 'open').mockImplementation(() => null)

        logic.actions.selectResult(result('https://posthog.com/docs'), false)

        expect(open).toHaveBeenCalledWith('https://posthog.com/docs', '_blank', 'noopener,noreferrer')
        expect(windows.values.windows).toHaveLength(1)
    })
})
