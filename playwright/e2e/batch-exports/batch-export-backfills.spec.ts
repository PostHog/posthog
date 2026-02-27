import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'

async function setupBackfillRoutes(
    page: Page,
    mockExportId: string,
    options: {
        backfillsOnList?: (callCount: number, submittedDates: { start_at: string; end_at: string }) => object
    } = {}
): Promise<void> {
    const mockExport = {
        id: mockExportId,
        team_id: 1,
        name: 'Test S3 Export',
        model: 'events',
        destination: {
            type: 'S3',
            config: {
                bucket_name: 'test-bucket',
                region: 'us-east-1',
                prefix: 'events/',
            },
        },
        interval: 'hour',
        timezone: null,
        offset_day: null,
        offset_hour: null,
        paused: false,
        created_at: '2024-01-01T00:00:00Z',
        last_updated_at: '2024-01-01T00:00:00Z',
        last_paused_at: null,
        start_at: null,
        end_at: null,
        latest_runs: [],
        filters: [],
    }

    await page.route(`**/api/environments/*/batch_exports/${mockExportId}/`, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockExport) })
    })

    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${mockExportId}/runs`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], next: null }),
            })
        }
    )

    let submittedDates: { start_at: string; end_at: string } | null = null
    let backfillListCallCount = 0
    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${mockExportId}/backfills`),
        async (route) => {
            if (route.request().method() === 'POST') {
                const postData = route.request().postDataJSON()
                submittedDates = { start_at: postData.start_at, end_at: postData.end_at }
                await route.fulfill({
                    status: 201,
                    contentType: 'application/json',
                    body: JSON.stringify({ backfill_id: 'temporal-workflow-id' }),
                })
            } else {
                // Only return backfills after a backfill has been created
                const response =
                    submittedDates && options.backfillsOnList
                        ? options.backfillsOnList(++backfillListCallCount, submittedDates)
                        : { results: [], next: null }
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(response),
                })
            }
        }
    )
}

test.describe('Batch export backfills', () => {
    test('Shows backfill estimate toast with cancel option after creating a backfill', async ({ page }) => {
        const mockExportId = '01234567-0123-0123-0123-0123456789ab'
        const mockBackfillId = 'backfill-001'

        await setupBackfillRoutes(page, mockExportId, {
            backfillsOnList: (callCount, { start_at, end_at }) => {
                if (callCount <= 2) {
                    // First 2 calls: backfill exists but no estimate yet
                    return {
                        results: [
                            {
                                id: mockBackfillId,
                                status: 'Starting',
                                created_at: new Date().toISOString(),
                                start_at,
                                end_at,
                            },
                        ],
                        next: null,
                    }
                }
                // After 2 calls: estimate becomes available
                return {
                    results: [
                        {
                            id: mockBackfillId,
                            status: 'Running',
                            created_at: new Date().toISOString(),
                            start_at,
                            end_at,
                            total_records_count: 42500,
                        },
                    ],
                    next: null,
                }
            },
        })

        // Navigate to the backfills tab
        await page.goto(`/pipeline/batch-exports/${mockExportId}?tab=backfills`)
        await expect(page.getByRole('button', { name: 'Start backfill', exact: true })).toBeVisible()

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
    })
})
