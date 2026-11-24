import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { METRICS } from './homeFixtures'
import { HomeHost } from './HomeHost'

type Answer = [number, unknown]

describe('HomeHost', () => {
    let metricsAnswer: Answer
    let dashboards: { id: number }[]
    let dashboardsCreated: number

    beforeEach(() => {
        metricsAnswer = [200, METRICS]
        dashboards = [{ id: 42 }]
        dashboardsCreated = 0
        useMocks({
            get: {
                '/api/projects/:team_id/ai_observability/traces/metrics/': () => metricsAnswer,
                '/api/projects/:team_id/dashboards/': () => [200, { count: dashboards.length, results: dashboards }],
            },
            post: {
                '/api/projects/:team_id/dashboards/create_unlisted_dashboard/': () => {
                    dashboardsCreated += 1
                    return [200, { id: 43 }]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.aiObservabilityDashboard())
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it('renders tiles, the four placeholders and the old dashboard link', async () => {
        const { container } = render(<HomeHost />)

        await waitFor(() => expect(container.textContent).toContain('52,118'))
        await waitFor(() => expect(container.querySelector('[data-attr="home-open-dashboard"]')).not.toBeNull())
        expect(container.querySelectorAll('[data-attr^="home-tile-"]')).toHaveLength(6)
        expect(container.querySelectorAll('[data-attr^="home-section-"]')).toHaveLength(4)
        expect(container.textContent).toContain('Compared with the previous period')
    })

    it('hides the dashboard link without creating a dashboard when there is none', async () => {
        dashboards = []
        const { container } = render(<HomeHost />)

        await waitFor(() => expect(container.textContent).toContain('52,118'))
        expect(container.querySelector('[data-attr="home-open-dashboard"]')).toBeNull()
        expect(dashboardsCreated).toBe(0)
    })

    it('shows the range banner for a range that is too long', async () => {
        silenceKeaLoadersErrors()
        metricsAnswer = [422, { detail: 'Pick a range of 90 days or less.', code: 'range_too_long' }]

        const view = render(<HomeHost />)

        expect(await view.findByText('Pick a range of 90 days or less.')).toBeTruthy()
        expect(view.container.querySelectorAll('[data-attr^="home-tile-"]')).toHaveLength(0)
        expect(view.queryByText('Compared with the previous period')).toBeNull()
    })

    it('shows a retry for any other failure', async () => {
        silenceKeaLoadersErrors()
        metricsAnswer = [500, { detail: 'boom' }]

        const view = render(<HomeHost />)

        expect(await view.findByText('Could not load the metrics')).toBeTruthy()
        expect(view.container.querySelector('[data-attr="home-metrics-retry"]')).not.toBeNull()
        expect(view.queryByText('Compared with the previous period')).toBeNull()
    })

    it.each([
        ['traces', 'Traces', '7,445 per day on average', true],
        ['cost', 'Cost', 'Spend across all models', false],
    ])('opens the %s chart under the tiles and closes it', async (slug, label, detail, linksToActivity) => {
        const { container } = render(<HomeHost />)
        const panel = (): Element | null => container.querySelector(`[data-attr="home-chart-${slug}"]`)
        await waitFor(() => expect(container.querySelector(`[data-attr="home-chart-${slug}-toggle"]`)).not.toBeNull())

        fireEvent.click(container.querySelector(`[data-attr="home-chart-${slug}-toggle"]`)!)

        expect(panel()?.textContent).toContain(`${label} · Last 7 days`)
        expect(panel()?.textContent).toContain(detail)
        expect(!!panel()?.querySelector(`[data-attr="home-chart-${slug}-activity"]`)).toBe(linksToActivity)
        expect(panel()?.querySelector(`[data-attr="home-chart-${slug}-insight"]`)?.getAttribute('href')).toContain(
            '/sql?open_query='
        )

        fireEvent.click(panel()!.querySelector(`[data-attr="home-chart-${slug}-close"]`)!)
        expect(panel()).toBeNull()
    })
})
