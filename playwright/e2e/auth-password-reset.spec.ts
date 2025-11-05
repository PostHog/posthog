import { LoginPage } from '../page-models/loginPage'
import { expect, test } from '../utils/playwright-test-base'

const VALID_PASSWORD = 'hedgE-hog-123%'

test.describe('Password Reset', () => {
    let loginPage: LoginPage

    test.beforeEach(async ({ page }) => {
        await page.click('[data-attr=menu-item-me]')
        await page.click('[data-attr=top-menu-item-logout]')
        await expect(page).toHaveURL('/login')
        loginPage = new LoginPage(page)
    })

    test('Can request password reset', async ({ page }) => {
        await loginPage.enterUsername('fake@posthog.com')
        await page.locator('[data-attr=login-email]').blur()
        await expect(page.locator('[data-attr=forgot-password]')).toBeVisible({ timeout: 5000 })
        await page.click('[data-attr="forgot-password"]')
        await expect(page).toHaveURL('/reset?email=fake%40posthog.com')
        await page.fill('[data-attr="reset-email"]', 'test@posthog.com')
        await page.click('button[type=submit]')
        await expect(page.getByText('Request received successfully!')).toBeVisible()
        await expect(page.getByText('test@posthog.com')).toBeVisible()
    })

    test('Cannot reset with invalid token', async ({ page }) => {
        await page.goto('/reset/user_id/token')
        await expect(page.getByText('The provided link is invalid or has expired.')).toBeVisible()
    })

    test('Shows validation error if passwords do not match', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', VALID_PASSWORD)
        await expect(page.locator('.LemonProgress__track')).toBeVisible()
        await page.fill('[data-attr="password-confirm"]', '1234567A')
        await page.click('button[type=submit]')
        await expect(page.getByText('Passwords do not match')).toBeVisible()
        await expect(page).toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })

    test('Shows validation error if password is too short', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', '123')
        await page.fill('[data-attr="password-confirm"]', '123')
        await page.click('button[type=submit]')
        await expect(page.getByText('Add another word or two')).toBeVisible()
        await expect(page.getByText('Add another word or two')).toHaveClass(/text-danger/)
        await expect(page).toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })

    test('Can reset password with valid token', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', VALID_PASSWORD)
        await page.fill('[data-attr="password-confirm"]', VALID_PASSWORD)

        // Intercept the password reset complete request to check response
        const responsePromise = page.waitForResponse(
            (response) => response.url().includes('/api/reset/e2e_test_user') && response.request().method() === 'POST'
        )

        await page.click('button[type=submit]')

        const response = await responsePromise
        expect(response.status()).toBe(200)
        const responseBody = await response.json()
        expect(responseBody.success).toBe(true)
        expect(responseBody.email).toBe('test@posthog.com')

        await expect(page.locator('.Toastify__toast--success')).toBeVisible()
        await expect(page).not.toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })
})
