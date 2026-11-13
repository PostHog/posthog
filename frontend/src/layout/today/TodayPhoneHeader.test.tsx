import { render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { TodayPhoneHeader } from './TodayPhoneHeader'
import { todayShellLogic } from './todayShellLogic'

describe('TodayPhoneHeader', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        todayShellLogic.mount()
    })

    test.each([
        ['home', true],
        ['analytics', false],
    ] as const)('on the %s pane, shows the project menu: %s', (pane, projectMenu) => {
        todayShellLogic.actions.clickRailPane(pane)

        const { container, unmount } = render(<TodayPhoneHeader />)

        expect(!!container.querySelector('[data-attr="today-top-bar-project-menu"]')).toBe(projectMenu)
        unmount()
    })
})
