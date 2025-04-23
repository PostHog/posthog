import { expect, test } from '../utils/playwright-test-base'

test.describe('Onboarding', () => {
    test.beforeEach(async ({ request }) => {
        // Reset onboarding state before each test
        await request.patch('/api/projects/1/', {
            data: { completed_snippet_onboarding: false },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    test('can complete product analytics onboarding', async ({ page }) => {
        await page.goto('/products')

        await expect(page.getByText('Product Analytics')).toBeVisible()

        await page.getByTestId('product_analytics-onboarding-card').click()

        await expect(page.getByText('Get started')).toBeVisible()

        await page.getByText('Get started').click()

        await expect(page).toHaveURL(/.*\/onboarding\/product_analytics\?step=install/)

        // Step 1: Install SDK
        await expect(page.getByRole('heading', { name: 'Install', level: 1 })).toBeVisible()

        // Verify SDK options are shown
        await expect(page.getByText('JavaScript Web')).toBeVisible()
        await expect(page.getByText('React Native')).toBeVisible()
        await expect(page.getByText('Node.js')).toBeVisible()

        await expect(page.getByTestId('sdk-continue')).toBeVisible()

        await page.getByTestId('sdk-continue').click()

        // Step 2: Product Configuration

        await expect(page).toHaveURL(/.*\/onboarding\/product_analytics\?step=configure/)

        await expect(page.getByText('Options')).toBeVisible()

        // Verify configuration options
        await expect(page.getByText('Autocapture frontend interactions')).toBeVisible()
        await expect(page.getByText('Enable heatmaps')).toBeVisible()
        await expect(page.getByText('Enable web vitals autocapture')).toBeVisible()

        const autocaptureSwitch = page.getByTestId('onboarding-product-configuration-toggle-0')
        await expect(autocaptureSwitch).toBeVisible()

        // // Set up request interception before clicking
        // const requestPromise = page.waitForRequest(request =>
        //   request.url().includes('/api/environments/**') &&
        //   request.method() === 'PATCH' &&
        //   JSON.stringify(request.postData()).includes('"autocapture_opt_out":true')
        // )

        await autocaptureSwitch.click()

        // // Wait for the request to be made
        // await requestPromise

        await expect(page.getByTestId('onboarding-continue')).toBeVisible()
        await page.getByTestId('onboarding-continue').click()

        // Step 3: Plans page

        await expect(page).toHaveURL(/.*\/onboarding\/product_analytics\?step=plans/)

        await expect(page.getByText('Select this plan')).toBeVisible()

        await page.getByText('Select this plan').click()

        // Step 4: Invite teammates
        await expect(page).toHaveURL(/.*\/onboarding\/product_analytics\?step=invite_teammates/)
        await expect(page.getByRole('heading', { name: 'Invite teammates', level: 1 })).toBeVisible()

        // Complete onboarding
        await page.getByTestId('onboarding-continue').click()

        // Verify we're redirected to the product
        await expect(page).toHaveURL(/.*\/insights\/new/)
    })
})
