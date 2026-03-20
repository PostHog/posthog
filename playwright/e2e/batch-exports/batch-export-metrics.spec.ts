import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'
import { createMockBatchExport, MOCK_EXPORT_ID, setupBatchExportRoutes } from './batch-export-helpers'

async function setupMetricsRoutes(page: Page): Promise<void> {
    await setupBatchExportRoutes(page, MOCK_EXPORT_ID, createMockBatchExport())

    // Mock query API for metrics queries
    await page.route(
        (url) => url.pathname.includes('/api/environments/') && url.pathname.includes('/query/'),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    results: [],
                    columns: [],
                    hasMore: false,
                }),
            })
        }
    )
}

test.describe('Batch export metrics', () => {
    test('Renders metrics content', async ({ page }) => {
        await setupMetricsRoutes(page)

        await page.goto(`/pipeline/batch-exports/${MOCK_EXPORT_ID}?tab=metrics`)

        // The metrics tab should render content
        await expect(page.getByText('Metrics').first()).toBeVisible()
    })
})
