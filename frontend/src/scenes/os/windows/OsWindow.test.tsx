import { MOCK_TEAM_ID } from 'lib/api.mock'

import { act, cleanup, render } from '@testing-library/react'
import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { OsWindow } from './OsWindow'
import { osWindowFramesLogic } from './osWindowFramesLogic'
import { osWindowsLogic } from './osWindowsLogic'

const INSIGHTS = `/project/${MOCK_TEAM_ID}/insights`
const REPLAY = `/project/${MOCK_TEAM_ID}/replay/home`

function Desktop(): JSX.Element {
    useMountedLogic(osWindowFramesLogic)
    const { windows, focusedWindow } = useValues(osWindowsLogic)
    return (
        <>
            {windows.map((w) => (
                <OsWindow
                    key={w.id}
                    window={w}
                    focused={w.id === focusedWindow?.id}
                    desktopElement={null}
                    interacting={false}
                    onInteractionChange={() => {}}
                    onSnapPreview={() => {}}
                />
            ))}
        </>
    )
}

describe('OsWindow', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        initKeaTests(true)
        router.actions.push(INSIGHTS)
    })

    afterEach(() => {
        cleanup()
    })

    function frameOf(container: HTMLElement, path: string): HTMLIFrameElement | null {
        const id = osWindowsLogic.values.windows.find((w) => w.path === path)?.id
        return container.querySelector(`[data-os-window-id="${id}"] iframe`)
    }

    it('keeps the same frame while the app loads, and while the window is minimized, restored or covered', () => {
        const { container } = render(<Desktop />)
        const frame = frameOf(container, INSIGHTS)
        const id = osWindowsLogic.values.windows[0].id

        expect(frame).not.toBeNull()
        expect(container.querySelector('[data-attr="os-window-frame-loading"]')).not.toBeNull()

        act(() => {
            osWindowsLogic.actions.windowNavigated(id, INSIGHTS, 'Insights')
            osWindowsLogic.actions.minimizeWindow(id)
            osWindowsLogic.actions.restoreWindow(id)
            osWindowsLogic.actions.openWindow(REPLAY)
            osWindowsLogic.actions.focusWindow(id)
        })

        expect(frameOf(container, INSIGHTS)).toBe(frame)
        expect(container.querySelector(`[data-os-window-id="${id}"] [data-attr="os-window-frame-loading"]`)).toBeNull()
    })

    it('shows a page that is not the app as soon as the frame loads it', () => {
        const { container } = render(<Desktop />)
        const frame = frameOf(container, INSIGHTS) as HTMLIFrameElement

        act(() => {
            frame.dispatchEvent(new Event('load'))
        })

        expect(container.querySelector('[data-attr="os-window-frame-loading"]')).toBeNull()
    })

    it('keeps the loading state when the frame loads the app, until the app reports', () => {
        const { container } = render(<Desktop />)
        const frame = frameOf(container, INSIGHTS) as HTMLIFrameElement
        const root = frame.contentDocument?.createElement('div') as HTMLDivElement
        root.id = 'root'
        frame.contentDocument?.replaceChildren(root)

        act(() => {
            frame.dispatchEvent(new Event('load'))
        })

        expect(container.querySelector('[data-attr="os-window-frame-loading"]')).not.toBeNull()
    })
})
