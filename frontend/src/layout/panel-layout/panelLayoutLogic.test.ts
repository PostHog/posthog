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
})
