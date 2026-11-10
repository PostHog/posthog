import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodayRailPane, todayShellLogic } from '~/layout/today/todayShellLogic'
import { initKeaTests } from '~/test/init'

import { PeopleSceneHeader } from './PeopleSceneHeader'

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: ({ name }: { name: string }) => <h1>{name}</h1>,
}))

describe('PeopleSceneHeader', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        [true, 'people', 'Cohorts', false, false],
        [true, 'products', 'People and groups', true, true],
        [false, 'people', 'Cohorts', true, false],
    ] as [boolean, TodayRailPane, string, boolean, boolean][])(
        'with today-rail-nav %s and the %s pane open, names the page %s, shows tabs: %s, tabs below the title: %s',
        (todayRailNav, pane, title, showsTabs, tabsBelowTitle) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
            })
            todayShellLogic.mount()
            todayShellLogic.actions.setPickedPane(pane)

            render(
                <Provider>
                    <PeopleSceneHeader activeKey="cohorts" name="Cohorts" resourceType={{ type: 'cohort' }} />
                </Provider>
            )

            const heading = screen.getByRole('heading')
            const firstTab = screen.queryAllByRole('tab')[0]
            expect(heading).toHaveTextContent(title)
            expect(!!firstTab).toBe(showsTabs)
            expect(!!firstTab && !!(heading.compareDocumentPosition(firstTab) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(
                tabsBelowTitle
            )
        }
    )
})
