import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import type { PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { TodayHomePage } from './TodayHomePage'
import { todayLogic } from './todayLogic'
import { makeHighlights, makePulseMetric } from './todayTestFixtures'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('./todayLogic', () => ({ todayLogic: { values: { homeScrollTop: null } }, reportIdFromPath: () => null }))
jest.mock('./todayHighlightsLogic', () => ({ todayHighlightsLogic: {} }))
jest.mock('./TodaySampleBanner', () => ({ TodaySampleBanner: () => null }))
jest.mock('./TodayForYou', () => ({ TodayForYou: () => null }))
jest.mock('./TodayRecents', () => ({ TodayRecents: () => null }))
jest.mock('./TodayPulseHoverCard', () => ({
    TodayPulseHoverCard: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
jest.mock('./TodaySparkline', () => ({ TodaySparkline: () => null }))

describe('TodayHomePage loading', () => {
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
    it('replaces only a completed number and keeps the other named loaders in place', () => {
        const metrics = ['Sign-ups', 'Payments', 'Active users', 'Uploads'].map((name, i) =>
            makePulseMetric({ key: `number:${i}`, name, value: i === 1 ? 0 : 120 })
        )
        const slots: PulseSlotApi[] = metrics.map((metric) => ({
            key: metric.key,
            name: metric.name,
            url: metric.url,
            interval: metric.interval,
            status: 'pending',
        }))
        const home = {
            greeting: 'Hello',
            now: Date.now(),
            isNewProject: false,
            recentObjects: [],
            returnFocusReportId: null,
            useSampleData: false,
        }
        const numbers = {
            currentProjectId: 1,
            highlights: makeHighlights({ status: 'computing', pulse_slots: slots }),
            highlightsLoading: false,
            highlightsFailed: false,
            highlightsPending: false,
            pulsePending: false,
            pulseTiles: [] as typeof metrics,
            pulseSlots: slots,
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
        const list = screen.getByRole('list')
        const cards = within(list).getAllByRole('listitem')
        expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual(
            metrics.map((metric) => `${metric.name}: Loading`)
        )
        expect(cards.every((card) => card.getAttribute('aria-busy') === 'true')).toBe(true)

        numbers.pulseTiles = [metrics[1]]
        numbers.pulseSlots = slots.map((slot, i) => ({ ...slot, status: i === 1 ? 'ready' : 'pending' }))
        view.rerender(<TodayHomePage />)

        expect(within(list).getAllByRole('listitem')).toEqual(cards)
        expect(within(cards[1]).getByText('0')).toBeVisible()
        expect(cards[1]).not.toHaveAttribute('aria-busy', 'true')
        expect([cards[0], cards[2], cards[3]].every((card) => card.getAttribute('aria-busy') === 'true')).toBe(true)
        expect(metrics.map((metric) => within(list).getByText(metric.name).textContent)).toEqual(
            metrics.map((metric) => metric.name)
        )
    })
})
