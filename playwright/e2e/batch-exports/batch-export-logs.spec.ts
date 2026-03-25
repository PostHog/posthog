import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'
import { createMockBatchExport, MOCK_EXPORT_ID, setupBatchExportRoutes } from './batch-export-helpers'

async function setupLogsRoutes(page: Page): Promise<void> {
    await setupBatchExportRoutes(page, MOCK_EXPORT_ID, createMockBatchExport())

    // Mock the logs API (used by LogsViewer or PipelineNodeLogs)
    await page.route(
        (url) => url.pathname.includes(`/batch_exports/${MOCK_EXPORT_ID}/logs`),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [] }),
            })
        }
    )

    // Mock the log entries query API used by the new LogsViewer
    await page.route(
        (url) => url.pathname.includes('/api/environments/') && url.pathname.includes('/query/'),
        async (route) => {
            const body = route.request().postDataJSON()
            // Only intercept log queries, let others pass through
            if (body?.query?.kind === 'LogsQuery' || body?.query?.kind === 'HogQLQuery') {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        results: [],
                        columns: [],
                        hasMore: false,
                    }),
                })
            } else {
                await route.continue()
            }
        }
    )
}

test.describe('Batch export logs', () => {
    test('Renders logs viewer', async ({ page }) => {
        await setupLogsRoutes(page)

        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=logs`)

        // The logs tab should render the LogsViewer with its search input
        await expect(page.getByPlaceholder('Search messages or invocation ID')).toBeVisible()
    })
})
