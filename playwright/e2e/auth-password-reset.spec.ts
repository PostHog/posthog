import { expect, test } from '../utils/playwright-test-base'
import { LoginPage } from '../page-models/loginPage'

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
        await expect(page).toHaveURL('/reset')
        await page.fill('[data-attr="reset-email"]', 'test@posthog.com')
        await page.click('button[type=submit]')
        await expect(page.locator('.BridgePage__content h2')).toContainText('Reset password')
        await expect(page.locator('.BridgePage__content')).toContainText('Request received successfully!')
        await expect(page.locator('.BridgePage__content')).toContainText('test@posthog.com')
    })

    test('Cannot reset with invalid token', async ({ page }) => {
        await page.goto('/reset/user_id/token')
        await expect(page.locator('.BridgePage__content .text-center')).toContainText(
            'The provided link is invalid or has expired.'
        )
    })

    test('Shows validation error if passwords do not match', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', VALID_PASSWORD)
        await expect(page.locator('.LemonProgress__track')).toBeVisible()
        await page.fill('[data-attr="password-confirm"]', '1234567A')
        await page.click('button[type=submit]')
        await expect(page.locator('.text-danger')).toContainText('Passwords do not match')
        await expect(page).toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })

    test('Shows validation error if password is too short', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', '123')
        await page.fill('[data-attr="password-confirm"]', '123')
        await page.click('button[type=submit]')
        await expect(page.locator('.text-danger')).toBeVisible()
        await expect(page.locator('.text-danger')).toContainText('Add another word or two')
        await expect(page).toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })

    test('Can reset password with valid token', async ({ page }) => {
        await page.goto('/reset/e2e_test_user/e2e_test_token')
        await page.fill('[data-attr="password"]', VALID_PASSWORD)
        await page.fill('[data-attr="password-confirm"]', VALID_PASSWORD)
        await page.click('button[type=submit]')
        await expect(page.locator('.Toastify__toast--success')).toBeVisible()
        await expect(page).not.toHaveURL('/reset/e2e_test_user/e2e_test_token')
    })
})
