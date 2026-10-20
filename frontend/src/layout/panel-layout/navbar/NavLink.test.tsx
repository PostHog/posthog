import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { initKeaTests } from '~/test/init'

import { NavLink } from './NavLink'

describe('NavLink', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    // A product can link to a filtered list, so its href carries a query string the pathname never has
    it.each([
        ['/project/1/views', true],
        ['/project/1/notebooks', false],
    ])('marks a link with a query-bearing href active on %s: %s', (path, expected) => {
        router.actions.push(path)
        panelLayoutLogic.mount()
        const { container } = render(
            <NavLink to="/views?type=canvas" label="Canvases" icon={null} isCollapsed={false} data-attr="nav-link" />
        )

        const link = container.querySelector('[data-attr="nav-link"]')!
        expect(link.classList.contains('button-primitive--active')).toBe(expected)
    })
})
