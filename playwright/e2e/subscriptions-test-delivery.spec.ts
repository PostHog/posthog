import { Page } from '@playwright/test'

import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

// End-to-end coverage for PR #66786: the "Test delivery" button on the subscription
// detail-page header. The subscription, its deliveries, and the test-delivery endpoint
// are route-mocked so the test is deterministic and doesn't need a seeded subscription —
// it exercises the real scene, kea logic, and button wiring in a browser.

const SUB_ID = 1
const HEADER_BTN = 'subscription-detail-header-test-delivery'

const mockSubscription = (): Record<string, unknown> => ({
    id: SUB_ID,
    resource_type: 'insight',
    insight: 101,
    dashboard: null,
    insight_short_id: 'abc123',
    resource_name: 'North star metric',
    title: 'Weekly rollup',
    dashboard_export_insights: [],
    target_type: 'email',
    target_value: 'a@b.com',
    frequency: 'weekly',
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'user-1', first_name: 'Test', email: 'test@posthog.com' },
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    enabled: true,
    deleted: false,
})

type TestDeliveryMocks = {
    // HTTP status the mocked test-delivery POST returns (202 success, 409 already-in-progress, etc.)
    postStatus?: number
    // When set, the POST response is held until this promise resolves — lets a test observe the in-flight state.
    postGate?: Promise<void>
}

async function setupSubscriptionMocks(
    page: Page,
    options: TestDeliveryMocks = {}
): Promise<{ postCount: () => number }> {
    const { postStatus = 202, postGate } = options
    let posts = 0

    await page.route(
        (url) => new RegExp(`/api/projects/[^/]+/subscriptions/${SUB_ID}/?$`).test(url.pathname),
        async (route) => {
            if (route.request().method() !== 'GET') {
                await route.continue()
                return
            }
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify(mockSubscription()),
            })
        }
    )

    await page.route(
        (url) => new RegExp(`/api/projects/[^/]+/subscriptions/${SUB_ID}/deliveries/?`).test(url.pathname),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], next: null, previous: null }),
            })
        }
    )

    await page.route(
        (url) => new RegExp(`/api/projects/[^/]+/subscriptions/${SUB_ID}/test-delivery/?$`).test(url.pathname),
        async (route) => {
            if (route.request().method() !== 'POST') {
                await route.continue()
                return
            }
            posts += 1
            if (postGate) {
                await postGate
            }
            await route.fulfill({ status: postStatus, contentType: 'application/json', body: '{}' })
        }
    )

    return { postCount: () => posts }
}

test.describe('Subscription detail — Test delivery header button', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('clicking Test delivery POSTs once and shows the success toast', async ({ page }) => {
        const { postCount } = await setupSubscriptionMocks(page, { postStatus: 202 })
        await page.goto(`/project/${workspace!.team_id}/subscriptions/${SUB_ID}`)

        const button = page.getByTestId(HEADER_BTN)
        await expect(button).toBeVisible({ timeout: 15000 })
        await expect(button).toHaveText(/test delivery/i)

        await button.click()

        await expect(page.getByText('Test delivery started')).toBeVisible({ timeout: 10000 })
        expect(postCount()).toBe(1)
    })

    test('button disables while the delivery is in flight (double-submit guard)', async ({ page }) => {
        let release: () => void = () => {}
        const gate = new Promise<void>((resolve) => {
            release = resolve
        })
        const { postCount } = await setupSubscriptionMocks(page, { postStatus: 202, postGate: gate })
        await page.goto(`/project/${workspace!.team_id}/subscriptions/${SUB_ID}`)

        const button = page.getByTestId(HEADER_BTN)
        await expect(button).toBeVisible({ timeout: 15000 })

        await button.click()

        // While the POST is held open the button reports itself disabled and shows the loading
        // spinner, so a user cannot fire a second delivery.
        await expect(button).toHaveAttribute('aria-disabled', 'true', { timeout: 10000 })
        await expect(button).toHaveClass(/LemonButton--loading/)

        release()

        await expect(page.getByText('Test delivery started')).toBeVisible({ timeout: 10000 })
        await expect(button).toHaveAttribute('aria-disabled', 'false', { timeout: 10000 })
        expect(postCount()).toBe(1)
    })

    test('shows a warning toast when a delivery is already in progress (409)', async ({ page }) => {
        await setupSubscriptionMocks(page, { postStatus: 409 })
        await page.goto(`/project/${workspace!.team_id}/subscriptions/${SUB_ID}`)

        const button = page.getByTestId(HEADER_BTN)
        await expect(button).toBeVisible({ timeout: 15000 })
        await button.click()

        await expect(page.getByText('Delivery already in progress')).toBeVisible({ timeout: 10000 })
    })

    test('shows an error toast and re-enables the button when the delivery fails (500)', async ({ page }) => {
        await setupSubscriptionMocks(page, { postStatus: 500 })
        await page.goto(`/project/${workspace!.team_id}/subscriptions/${SUB_ID}`)

        const button = page.getByTestId(HEADER_BTN)
        await expect(button).toBeVisible({ timeout: 15000 })
        await button.click()

        await expect(page.getByText('Failed to deliver subscription')).toBeVisible({ timeout: 10000 })
        // The in-flight guard must release on failure too, or the button stays stuck disabled.
        await expect(button).toHaveAttribute('aria-disabled', 'false', { timeout: 10000 })
    })
})
