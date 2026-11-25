import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { clearCachedChecklistVerdict } from '../../instrumentationChecklist/instrumentationChecklistLogic'
import { makePersonListPage, PEOPLE_URL } from '../people/testFixtures'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { CHECKLIST_ALL_OK, CHECKLIST_WARNING, METRICS } from './homeFixtures'
import { HomeHost } from './HomeHost'

type Answer = [number, unknown]

describe('HomeHost', () => {
    let metricsAnswer: Answer
    let peopleAnswer: Answer
    let peopleGate: Promise<void>
    let dashboards: { id: number }[]
    let dashboardsCreated: number
    let dismissBodies: unknown[]
    let checklistRefreshes: (string | null)[]

    beforeEach(() => {
        clearCachedChecklistVerdict()
        dismissBodies = []
        checklistRefreshes = []
        metricsAnswer = [200, METRICS]
        peopleAnswer = [200, makePersonListPage(['p1', 'p2'])]
        peopleGate = Promise.resolve()
        dashboards = [{ id: 42 }]
        dashboardsCreated = 0
        useMocks({
            get: {
                '/api/projects/:team_id/ai_observability/traces/metrics/': () => metricsAnswer,
                [PEOPLE_URL]: async () => {
                    await peopleGate
                    return peopleAnswer
                },
                '/api/projects/:team_id/ai_observability/instrumentation_checklist/': ({ request }) => {
                    const refresh = new URL(request.url).searchParams.get('refresh')
                    checklistRefreshes.push(refresh)
                    return [200, refresh === 'true' ? CHECKLIST_ALL_OK : CHECKLIST_WARNING]
                },
                '/api/projects/:team_id/dashboards/': () => [200, { count: dashboards.length, results: dashboards }],
            },
            post: {
                '/api/projects/:team_id/ai_observability/instrumentation_checklist/dismiss/': async ({ request }) => {
                    dismissBodies.push(await request.json())
                    return [200, CHECKLIST_ALL_OK]
                },
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

    it('renders tiles, the three placeholders, the expensive users and the old dashboard link', async () => {
        const { container } = render(<HomeHost />)

        await waitFor(() => expect(container.textContent).toContain('52,118'))
        await waitFor(() => expect(container.querySelector('[data-attr="home-open-dashboard"]')).not.toBeNull())
        expect(container.querySelectorAll('[data-attr^="home-tile-"]')).toHaveLength(6)
        expect(container.querySelectorAll('[data-attr^="home-section-"]')).toHaveLength(4)
        await waitFor(() => expect(container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(2))
        expect(container.querySelector('[data-attr="home-expensive-people-view-all"]')?.getAttribute('href')).toContain(
            '/ai-observability/users?'
        )
        expect(container.textContent).toContain('Compared with the previous period')
        await waitFor(() => expect(container.querySelector('[data-attr="home-instrumentation"]')).not.toBeNull())
    })

    it('dismisses a check through the shared checklist and installs its recomputed answer', async () => {
        const { container } = render(<HomeHost />)
        const dismiss = await waitFor(() => {
            const button = container.querySelector('[data-attr="ai-observability-instrumentation-checklist-dismiss"]')
            expect(button).not.toBeNull()
            return button as HTMLElement
        })

        fireEvent.click(dismiss)

        await waitFor(() => expect(container.querySelector('[data-attr="home-instrumentation"]')).toBeNull())
        expect(dismissBodies).toEqual([{ check: 'sessions' }])
    })

    it('re-checks the shared checklist from the row and installs the fresh answer', async () => {
        const { container } = render(<HomeHost />)
        const refresh = await waitFor(() => {
            const button = container.querySelector('[data-attr="home-instrumentation-refresh"]')
            expect(button).not.toBeNull()
            return button as HTMLElement
        })

        fireEvent.click(refresh)

        await waitFor(() => expect(container.querySelector('[data-attr="home-instrumentation"]')).toBeNull())
        expect(checklistRefreshes.at(-1)).toBe('true')
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

    it('shows the people skeleton, not the old rows, while a new range loads', async () => {
        const view = render(<HomeHost />)
        await waitFor(() =>
            expect(view.container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(2)
        )

        let release = (): void => {}
        peopleGate = new Promise((resolve) => (release = resolve))
        peopleAnswer = [200, makePersonListPage(['p1'])]
        shellScopeLogic.actions.setDateRange('-7d', null)

        await waitFor(() =>
            expect(view.container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(0)
        )
        release()
        await waitFor(() =>
            expect(view.container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(1)
        )
        shellScopeLogic.actions.setDateRange('-24h', null)
    })

    it('retries a failed people read without touching the tiles', async () => {
        silenceKeaLoadersErrors()
        peopleAnswer = [500, { detail: 'boom' }]
        const view = render(<HomeHost />)
        const retry = await waitFor(() => {
            const button = view.container.querySelector('[data-attr="home-expensive-people-retry"]')
            expect(button).not.toBeNull()
            return button as HTMLElement
        })
        expect(view.container.textContent).toContain('52,118')

        peopleAnswer = [200, makePersonListPage(['p1'])]
        fireEvent.click(retry)

        await waitFor(() =>
            expect(view.container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(1)
        )
    })

    it.each([
        ['traces', 'Traces', '7,445 per day on average', true],
        ['cost', 'Cost', 'Spend across all models', false],
    ])('opens the %s chart under the tiles and closes it', async (slug, label, detail, linksToActivity) => {
        const { container } = render(<HomeHost />)
        const panel = (): Element | null => container.querySelector(`[data-attr="home-chart-${slug}"]`)
        await waitFor(() => expect(container.querySelector(`[data-attr="home-chart-${slug}-toggle"]`)).not.toBeNull())

        fireEvent.click(container.querySelector(`[data-attr="home-chart-${slug}-toggle"]`)!)

        expect(panel()?.textContent).toContain(`${label} · Last 24 hours`)
        expect(panel()?.textContent).toContain(detail)
        expect(!!panel()?.querySelector(`[data-attr="home-chart-${slug}-activity"]`)).toBe(linksToActivity)
        expect(panel()?.querySelector(`[data-attr="home-chart-${slug}-insight"]`)?.getAttribute('href')).toContain(
            '/sql?open_query='
        )

        fireEvent.click(panel()!.querySelector(`[data-attr="home-chart-${slug}-close"]`)!)
        expect(panel()).toBeNull()
    })
})
