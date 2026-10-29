import { cleanup, render } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { TodayHomePage } from './TodayHomePage'
import { todayLogic } from './todayLogic'
import { makeHighlights, makePulseMetric } from './todayTestFixtures'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('./todayLogic', () => ({ todayLogic: { values: { homeScrollTop: null } }, reportIdFromPath: () => null }))
jest.mock('./todayHighlightsLogic', () => ({ todayHighlightsLogic: {} }))
jest.mock('./TodaySampleBanner', () => ({ TodaySampleBanner: () => null }))
jest.mock('./TodayForYou', () => ({ TodayForYou: () => null }))
jest.mock('./TodayRecents', () => ({ TodayRecents: () => null }))
jest.mock('./TodayPulse', () => ({ TodayPulse: () => null }))

describe('TodayHomePage load measurement', () => {
    afterEach(cleanup)

    it('evaluates existing numbers when leaving sample mode', () => {
        const home = {
            greeting: 'Hello',
            now: Date.now(),
            isNewProject: false,
            recentObjects: [],
            returnFocusReportId: null,
            useSampleData: true,
        }
        const numbers = {
            currentProjectId: 1,
            highlights: makeHighlights({ pulse: [makePulseMetric()] }),
            highlightsLoading: false,
            highlightsFailed: false,
            highlightsPending: false,
            pulseTiles: [makePulseMetric()],
            pulsePinsLoaded: false,
        }
        const actions = {
            setReturnFocusReportId: jest.fn(),
            pulseViewMounted: jest.fn(),
            pulseViewUpdated: jest.fn(),
            pulseViewUnmounted: jest.fn(),
        }
        jest.mocked(useValues).mockImplementation((logic) => (logic === todayLogic ? home : numbers))
        jest.mocked(useActions).mockImplementation(() => actions)

        const view = render(<TodayHomePage />)
        actions.pulseViewUpdated.mockClear()
        home.useSampleData = false
        view.rerender(<TodayHomePage />)

        expect(actions.pulseViewMounted).toHaveBeenLastCalledWith(false)
        expect(actions.pulseViewUpdated).toHaveBeenCalledTimes(1)
    })
})
