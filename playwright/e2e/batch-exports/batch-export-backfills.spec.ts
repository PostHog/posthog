import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'
import { createMockBatchExport, MOCK_EXPORT_ID, setupBatchExportRoutes } from './batch-export-helpers'

async function setupBackfillRoutes(
    page: Page,
    options: {
        backfillOnGet?: (callCount: number) => object | null
    } = {}
): Promise<void> {
    await setupBatchExportRoutes(page, MOCK_EXPORT_ID, createMockBatchExport())

    const mockBackfillId = 'backfill-001'

    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_EXPORT_ID}/runs`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], next: null }),
            })
        }
    )

    let backfillGetCallCount = 0
    let backfillCreated = false

    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_EXPORT_ID}/backfills`),
        async (route) => {
            const url = route.request().url()

            if (route.request().method() === 'POST') {
                backfillCreated = true
                await route.fulfill({
                    status: 201,
                    contentType: 'application/json',
                    body: JSON.stringify({ backfill_id: mockBackfillId }),
                })
            } else if (url.includes(`/backfills/${mockBackfillId}/`)) {
                // Individual backfill GET (polling for estimate)
                const response =
                    backfillCreated && options.backfillOnGet ? options.backfillOnGet(++backfillGetCallCount) : null
                if (response) {
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify(response),
                    })
                } else {
                    await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
                }
            } else {
                // List backfills
                const results = backfillCreated
                    ? [
                          {
                              id: mockBackfillId,
                              status: 'Running',
                              created_at: new Date().toISOString(),
                              start_at: '2026-01-10T00:00:00Z',
                              end_at: '2026-01-15T00:00:00Z',
                          },
                      ]
                    : []
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ results, next: null }),
                })
            }
        }
    )
}

test.describe('Batch export backfills', () => {
    test('Shows backfill estimate toast with cancel option after creating a backfill', async ({ page }) => {
        await setupBackfillRoutes(page, {
            backfillOnGet: (callCount) => {
                if (callCount <= 2) {
                    // First 2 calls: backfill exists but no estimate yet
                    return {
                        id: 'backfill-001',
                        status: 'Starting',
                        created_at: new Date().toISOString(),
                        start_at: '2026-01-10T00:00:00Z',
                        end_at: '2026-01-15T00:00:00Z',
                    }
                }
                // After 2 calls: estimate becomes available
                return {
                    id: 'backfill-001',
                    status: 'Running',
                    created_at: new Date().toISOString(),
                    start_at: '2026-01-10T00:00:00Z',
                    end_at: '2026-01-15T00:00:00Z',
                    total_records_count: 42500,
                }
            },
        })

        // Navigate to the backfills tab
        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=backfills`)
        await expect(page.getByRole('button', { name: 'Start backfill', exact: true }).first()).toBeVisible()

        // Open the backfill modal and submit
        await page.getByRole('button', { name: 'Start backfill', exact: true }).first().click()
        await expect(page.getByRole('dialog')).toBeVisible()

        // Select a start date
        // (Go back one month to avoid edge case where start date equals the auto-set end date)
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

        // Verify the estimate toast appears (polling finds the estimate after a few seconds)
        await expect(page.locator('[data-attr="info-toast"]')).toContainText('Estimated ~42,500 rows to export', {
            timeout: 15000,
        })

        // Verify the cancel button exists on the estimate toast
        await expect(
            page.locator('[data-attr="info-toast"]').getByRole('button', { name: 'Cancel backfill' })
        ).toBeVisible()

        // Verify batch export context uses "Total rows" (not "Total events")
        await expect(page.getByRole('cell', { name: 'Total rows' })).toBeVisible()
    })
})
