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
        ['/project/1/home', true],
        ['/project/1/home/reports/abc', false],
        ['/project/1/insights', false],
    ])('on %s, mounts one project menu, in the header: %s', (pathname, inHeader) => {
        router.actions.push(pathname)

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
