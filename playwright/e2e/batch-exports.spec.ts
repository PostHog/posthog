import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Batch Exports', () => {
    test('Create new S3 batch export', async ({ page }) => {
        const name = randomString('S3 Export')
        const mockId = '01234567-0123-0123-0123-0123456789ab'

        // Mock the batch export creation endpoint (requires Temporal in real env)
        await page.route('**/api/environments/*/batch_exports/', async (route) => {
            if (route.request().method() === 'POST') {
                const body = route.request().postDataJSON()
                await route.fulfill({
                    status: 201,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        id: mockId,
                        team_id: 1,
                        name: body.name,
                        model: 'events',
                        destination: {
                            type: 'S3',
                            config: {
                                bucket_name: body.destination.config.bucket_name,
                                region: body.destination.config.region,
                                prefix: body.destination.config.prefix,
                            },
                        },
                        interval: body.interval,
                        paused: false,
                        created_at: new Date().toISOString(),
                        last_updated_at: new Date().toISOString(),
                        last_paused_at: null,
                        start_at: null,
                        end_at: null,
                        latest_runs: [],
                        hogql_query: null,
                        schema: null,
                    }),
                })
            } else {
                await route.continue()
            }
        })

        await page.goto('/pipeline/batch-exports/new/s3')
        await expect(page.locator('.scene-name')).toContainText('S3')

        // Edit the name of the batch export
        await page.click('.scene-name button')
        await page.getByTestId('scene-title-textarea').fill(name)

        // Choose an interval
        await page.locator('button[name="interval"]').click()
        await page.getByRole('menuitem', { name: 'Hourly' }).click()

        // Fill in the S3 batch export form
        await page.locator('input[name="bucket_name"]').fill('my-test-bucket')

        // Region is a LemonSelect dropdown - find it via its parent Field
        await page
            .locator('.Field')
            .filter({ hasText: /^Region/ })
            .locator('button')
            .click()
        await page.getByRole('menuitem', { name: 'US East (N. Virginia)' }).click()

        await page.locator('input[name="prefix"]').fill('events/')
        await page.locator('input[name="aws_access_key_id"]').fill('AKIAIOSFODNN7EXAMPLE')
        await page.locator('input[name="aws_secret_access_key"]').fill('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')

        await page.locator('form').getByRole('button', { name: 'Create' }).click()
        await expect(page.locator('[data-attr="success-toast"]')).toContainText('Batch export created successfully')
    })

    test('Validate required fields prevent save', async ({ page }) => {
        await page.goto('/pipeline/batch-exports/new/s3')
        await expect(page.locator('.scene-name')).toContainText('S3')

        // Create button should be disabled when required fields are empty
        await expect(page.locator('form').getByRole('button', { name: 'Create' })).toBeDisabled()
    })
})
