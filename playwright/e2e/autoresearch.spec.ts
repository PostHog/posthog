import { expect } from '@playwright/test'

import { test } from '../utils/playwright-test-core'

const PIPELINE_LIST_PATH = '/api/projects/@current/autoresearch/'

interface AutoresearchPipelineSummary {
    id: string
    name: string
    status: string
}

test.describe('Autoresearch', () => {
    test('list scene loads and links into pipeline detail with all tabs', async ({ page }) => {
        // The product is gated behind the `autoresearch` feature flag and an existing pipeline.
        // The test asserts that whatever the local backend reports, the UI renders without
        // hitting the empty state and that every tab on pipeline detail mounts cleanly.
        const listResponse = await page.request.get(PIPELINE_LIST_PATH)
        expect(listResponse.ok(), 'autoresearch list endpoint should be reachable').toBeTruthy()
        const listBody = await listResponse.json()
        const pipelines = (listBody.results ?? []) as AutoresearchPipelineSummary[]
        test.skip(pipelines.length === 0, 'no autoresearch pipeline in local DB to drive the test')

        const pipeline = pipelines[0]

        await page.goto('/project/1/autoresearch')
        await expect(page.getByRole('heading', { name: 'Autoresearch' })).toBeVisible()
        await expect(page.getByRole('link', { name: pipeline.name })).toBeVisible()

        await page.getByRole('link', { name: pipeline.name }).click()
        await page.waitForURL(`**/autoresearch/${pipeline.id}`)

        const tabs = ['Overview', 'Training', 'Models', 'Predictions', 'Online performance', 'Runs', 'Settings']
        for (const tab of tabs) {
            await page.getByRole('tab', { name: tab, exact: true }).click()
            await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true')
        }
    })
})
