import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from './panelLayoutLogic'

describe('panelLayoutLogic', () => {
    beforeEach(() => {
        initKeaTests()
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
    })

    it.each(['dismiss', 'select', 'navigate'] as const)(
        'keeps the sidebar collapsed after closing its temporary overlay via %s',
        async (method) => {
            panelLayoutLogic.actions.setNavOverlayOpen(true)
            expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)

            await expectLogic(panelLayoutLogic, () => {
                if (method === 'dismiss') {
                    panelLayoutLogic.actions.setNavOverlayOpen(false)
                } else if (method === 'select') {
                    panelLayoutLogic.actions.resetPanelLayout(false)
                } else {
                    router.actions.push('/project/1/insights')
                }
            }).toMatchValues({ isNavOverlayOpen: false, isLayoutNavCollapsed: true })
        }
    )

    // Regression: a scene that collapses the nav for itself must not write the saved choice. A write
    // leaves the nav collapsed on every other screen, and so does a toggle made inside that scene.
    // A late clear from another scene must not expand the nav under the scene that owns the override.
    it('collapses for a scene without changing the saved choice', () => {
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(false)

        panelLayoutLogic.actions.setLayoutNavCollapsedOverride('scene-a', true)
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)

        panelLayoutLogic.actions.toggleLayoutNavCollapsed()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)
        expect(panelLayoutLogic.values.isLayoutNavCollapsedDesktop).toBe(false)

        panelLayoutLogic.actions.setLayoutNavCollapsedOverride('scene-b', null)
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)
        panelLayoutLogic.actions.setLayoutNavCollapsedOverride('scene-a', null)
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)
    })

    it('clears the temporary overlay when the sidebar is permanently expanded', async () => {
        panelLayoutLogic.actions.setNavOverlayOpen(true)
        await expectLogic(panelLayoutLogic, () =>
            panelLayoutLogic.actions.toggleLayoutNavCollapsed(false)
        ).toMatchValues({
            isNavOverlayOpen: false,
            isLayoutNavCollapsed: false,
        })
    })

    it('defers scene geometry during a sidebar drag and cancels pending measurements when the ref changes', () => {
        jest.useFakeTimers()
        const originalObserver = global.ResizeObserver
        let notify: ResizeObserverCallback = () => {}
        const disconnect = jest.fn()
        global.ResizeObserver = jest.fn().mockImplementation((callback: ResizeObserverCallback) => {
            notify = callback
            return { observe: jest.fn(), disconnect }
        })
        const container = document.createElement('main')
        const bounds = jest.spyOn(container, 'getBoundingClientRect')
        bounds.mockReturnValue({ width: 1200 } as DOMRect)

        try {
            panelLayoutLogic.actions.setMainContentRef({ current: container })
            expect(panelLayoutLogic.values.mainContentRect?.width).toBe(1200)
            bounds.mockReturnValue({ width: 1100 } as DOMRect)
            notify([], {} as ResizeObserver)
            expect(panelLayoutLogic.values.mainContentRect?.width).toBe(1100)

            document.body.classList.add('is-resizing')
            bounds.mockReturnValue({ width: 900 } as DOMRect)
            notify([], {} as ResizeObserver)
            jest.advanceTimersByTime(500)
            expect(panelLayoutLogic.values.mainContentRect?.width).toBe(1100)
            document.body.classList.remove('is-resizing')
            jest.advanceTimersByTime(100)
            expect(panelLayoutLogic.values.mainContentRect?.width).toBe(900)

            document.body.classList.add('is-resizing')
            notify([], {} as ResizeObserver)
            panelLayoutLogic.actions.setMainContentRef({ current: container })
            expect(disconnect).toHaveBeenCalledTimes(1)
            expect(jest.getTimerCount()).toBe(0)
            notify([], {} as ResizeObserver)
            panelLayoutLogic.actions.setMainContentRef(null)
            expect(disconnect).toHaveBeenCalledTimes(2)
            expect(jest.getTimerCount()).toBe(0)
        } finally {
            document.body.classList.remove('is-resizing')
            global.ResizeObserver = originalObserver
            jest.useRealTimers()
            bounds.mockRestore()
        }
    })
})
