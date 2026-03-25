import { Page } from '@playwright/test'

import { mockFeatureFlags } from '../../utils/mockApi'
import { expect, test } from '../../utils/playwright-test-base'
import { createMockBatchExport, setupBatchExportRoutes } from '../batch-exports/batch-export-helpers'

const MOCK_HOG_FUNCTION_ID = 'hog-func-001'
const MOCK_BATCH_EXPORT_ID = 'batch-export-from-hog-func'

async function setupHogFunctionBackfillRoutes(page: Page): Promise<void> {
    const mockHogFunction = {
        id: MOCK_HOG_FUNCTION_ID,
        type: 'destination',
        name: 'Test Destination',
        description: 'A test destination with backfills',
        enabled: true,
        deleted: false,
        hog: '',
        bytecode: [],
        inputs_schema: [],
        inputs: {},
        filters: {},
        icon_url: null,
        template: null,
        status: { state: 0, ratings: [], states: [] },
        created_at: '2026-01-01T00:00:00Z',
        created_by: { id: 1, uuid: 'user-001', distinct_id: 'user-001', first_name: 'Test', email: 'test@posthog.com' },
        updated_at: '2026-01-01T00:00:00Z',
        batch_export_id: MOCK_BATCH_EXPORT_ID,
    }

    // Mock hog function API
    await page.route(
        (url) => url.pathname.includes(`/hog_functions/${MOCK_HOG_FUNCTION_ID}`),
        async (route) => {
            if (route.request().method() === 'GET') {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockHogFunction),
                })
            } else {
                await route.continue()
            }
        }
    )

    // Enable backfill feature flag using the shared utility
    await mockFeatureFlags(page, {
        'backfill-workflows-destination': true,
    })

    // Mock batch export routes
    const mockBatchExport = createMockBatchExport({ id: MOCK_BATCH_EXPORT_ID })
    await setupBatchExportRoutes(page, MOCK_BATCH_EXPORT_ID, mockBatchExport)

    // Mock batch export backfills API
    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    results: [
                        {
                            id: 'backfill-001',
                            status: 'Completed',
                            created_at: '2026-01-15T10:00:00Z',
                            start_at: '2026-01-10T00:00:00Z',
                            end_at: '2026-01-15T00:00:00Z',
                        },
                    ],
                    next: null,
                }),
            })
        }
    )

    // Mock batch export runs API
    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_BATCH_EXPORT_ID}/runs`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], next: null }),
            })
        }
    )
}

test.describe('Hog function backfills tab', () => {
    test('Renders backfills table when navigating to backfills tab on a hog function destination', async ({ page }) => {
        await setupHogFunctionBackfillRoutes(page)

        // Navigate to the hog function page
        await page.goto(`/functions/${MOCK_HOG_FUNCTION_ID}`)

        // First verify the Backfills tab is visible (requires feature flag)
        const backfillsTab = page.getByRole('tab', { name: 'Backfills' })
        await expect(backfillsTab).toBeVisible({ timeout: 10000 })

        // Click the Backfills tab
        await backfillsTab.click()

        await expect(page.getByText('Completed')).toBeVisible({ timeout: 10000 })
    })
})
