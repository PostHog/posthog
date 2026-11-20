import { render } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { TodayPhoneHeader } from './TodayPhoneHeader'
import { todayShellLogic } from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'

describe('TodayPhoneHeader', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        todayShellLogic.mount()
    })

    test.each([
        { label: 'Home', pathname: '/project/1/home', pane: null, inHeader: true },
        { label: 'the Products pane over Home', pathname: '/project/1/home', pane: 'products', inHeader: false },
        { label: 'a Home report', pathname: '/project/1/home/reports/abc', pane: null, inHeader: false },
        { label: 'Insights', pathname: '/project/1/insights', pane: null, inHeader: false },
    ] as const)('on $label, mounts one project menu, in the header: $inHeader', ({ pathname, pane, inHeader }) => {
        router.actions.push(pathname)
        if (pane) {
            todayShellLogic.actions.clickRailPane(pane)
        }

        const { container, unmount } = render(
            <>
                <TodayPhoneHeader />
                <TodaySidebarFooter />
            </>
        )

        expect(container.querySelectorAll('[data-attr="today-top-bar-project-menu"]')).toHaveLength(1)
        expect(!!container.querySelector('.TodayPhoneHeader [data-attr="today-top-bar-project-menu"]')).toBe(inHeader)
        unmount()
    })
})
