import { Page } from '@playwright/test'

export const MOCK_EXPORT_ID = '01234567-0123-0123-0123-0123456789ab'

export function createMockBatchExport(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        id: MOCK_EXPORT_ID,
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
        created_at: '2026-01-01T00:00:00Z',
        last_updated_at: '2026-01-01T00:00:00Z',
        last_paused_at: null,
        start_at: null,
        end_at: null,
        latest_runs: [],
        filters: [],
        ...overrides,
    }
}

/**
 * Sets up the common routes needed for any batch export scene test:
 * - GET /batch_exports/:id/ → mock config
 * - GET /batch_exports/test/ → empty test steps
 */
export async function setupBatchExportRoutes(
    page: Page,
    exportId: string,
    mockExport: Record<string, unknown>
): Promise<void> {
    await page.route(`**/api/environments/*/batch_exports/${exportId}/`, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockExport) })
    })

    await page.route('**/api/environments/*/batch_exports/test/', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ steps: [] }) })
    })
}
