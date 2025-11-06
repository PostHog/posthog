import { expect, test } from '../utils/playwright-test-base'

test.describe('Before Onboarding', () => {
    test.beforeAll(async ({ request }) => {
        await request.patch('/api/projects/1/', {
            data: { completed_snippet_onboarding: false },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    test.afterAll(async ({ request }) => {
        await request.patch('/api/projects/1/', {
            data: { completed_snippet_onboarding: true },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    test('Navigate to a settings page even when a product has not been set up', async ({ page }) => {
        await page.goto('/settings/user')
        await expect(page.locator('.scene-tab-row .scene-tab-title')).toContainText('User')

        await page.goto('/settings/organization')
        await expect(page.locator('.scene-tab-row .scene-tab-title')).toContainText('Organization')
    })
})
