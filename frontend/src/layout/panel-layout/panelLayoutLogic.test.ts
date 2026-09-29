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
