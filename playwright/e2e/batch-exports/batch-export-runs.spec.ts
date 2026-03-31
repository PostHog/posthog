import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'
import { createMockBatchExport, MOCK_EXPORT_ID, setupBatchExportRoutes } from './batch-export-helpers'

async function setupRunsRoutes(
    page: Page,
    options: {
        runs?: object[]
        paused?: boolean
    } = {}
): Promise<void> {
    const mockExport = createMockBatchExport({ paused: options.paused ?? false })
    await setupBatchExportRoutes(page, MOCK_EXPORT_ID, mockExport)

    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_EXPORT_ID}/runs`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: options.runs ?? [], next: null }),
            })
        }
    )

    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_EXPORT_ID}/backfills`),
        async (route) => {
            if (route.request().method() === 'POST') {
                await route.fulfill({
                    status: 201,
                    contentType: 'application/json',
                    body: JSON.stringify({ backfill_id: 'backfill-from-runs' }),
                })
            } else {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ results: [], next: null }),
                })
            }
        }
    )
}

test.describe('Batch export runs', () => {
    test('Renders empty runs table', async ({ page }) => {
        await setupRunsRoutes(page)

        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=runs`)
        await expect(page.getByText('No runs in this time range.')).toBeVisible()
    })

    test('Renders runs with data', async ({ page }) => {
        await setupRunsRoutes(page, {
            runs: [
                {
                    id: 'run-001',
                    status: 'Completed',
                    created_at: '2026-01-15T10:00:00Z',
                    data_interval_start: '2026-01-15T09:00:00Z',
                    data_interval_end: '2026-01-15T10:00:00Z',
                },
                {
                    id: 'run-002',
                    status: 'Failed',
                    created_at: '2026-01-15T09:00:00Z',
                    data_interval_start: '2026-01-15T08:00:00Z',
                    data_interval_end: '2026-01-15T09:00:00Z',
                },
            ],
        })

        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=runs`)

        // Verify runs table renders with status indicators
        await expect(page.getByText('Completed')).toBeVisible()
        await expect(page.getByText('Failed')).toBeVisible()

        // Verify batch export context uses "Rows exported" (not "Events exported")
        await expect(page.getByRole('cell', { name: 'Rows exported' })).toBeVisible()

        // Verify "Bytes exported" column is shown for batch exports
        await expect(page.getByRole('cell', { name: 'Bytes exported' })).toBeVisible()
    })

    test('Creates a backfill successfully from runs tab', async ({ page }) => {
        await setupRunsRoutes(page)

        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=runs`)

        // Open the backfill modal
        await page.getByRole('button', { name: 'Start backfill' }).click()
        await expect(page.getByRole('dialog')).toBeVisible()

        // Select a start date (go back one month to avoid start == end edge case)
        await page.getByRole('dialog').getByRole('button', { name: 'Select start date' }).click()
        await page.locator('[data-attr="lemon-calendar-month-previous"]').click()
        await page
            .locator('[data-attr="lemon-calendar-select"]')
            .getByRole('button', { name: '1', exact: true })
            .first()
            .click()
        await page.locator('[data-attr="lemon-calendar-select-apply"]').click()

        // Submit the backfill form
        await page.getByRole('dialog').getByRole('button', { name: 'Schedule runs' }).click()

        // Verify the success toast appears
        await expect(page.locator('[data-attr="success-toast"]')).toContainText('Backfill created')
    })
})
