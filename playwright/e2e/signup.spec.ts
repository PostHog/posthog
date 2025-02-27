import { expect, test } from '../utils/playwright-test-base'

const VALID_PASSWORD = 'hedgE-hog-123%'

test.describe('Signup', () => {
    test.beforeEach(async ({ page }) => {
        // log out
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-item-logout]').click()
        await expect(page).toHaveURL('/login')

        await page.goto('/signup')
    })

    test('Cannot create account with existing email', async ({ page }) => {
        await page.fill('[data-attr=signup-email]', 'test@posthog.com')
        await page.fill('[data-attr=password]', VALID_PASSWORD)
        await page.click('[data-attr=signup-start]')
        await page.fill('[data-attr=signup-name]', 'Jane Doe')
        await page.fill('[data-attr=signup-organization-name]', 'Hogflix Movies')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()

        await page.click('[data-attr=signup-submit]')
        await expect(page.locator('.LemonBanner')).toContainText('There is already an account with this email address.')
    })

    test('Cannot signup without required attributes', async ({ page }) => {
        await page.click('[data-attr=signup-start]')
        await expect(page.locator('.text-danger')).toContainText('Please enter your email to continue')
        await expect(page.locator('.text-danger')).toContainText('Please enter your password to continue')
    })

    test('Cannot signup with invalid attributes', async ({ page }) => {
        await page.fill('[data-attr=password]', '123')
        await page.click('[data-attr=signup-start]')
        await expect(page.locator('.text-danger')).toContainText('Add another word or two')

        // etc.
    })

    test('Can create user account with first name, last name, and organization name', async ({ page }) => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        await page.fill('[data-attr=signup-email]', email)
        await page.fill('[data-attr=password]', VALID_PASSWORD)
        await page.click('[data-attr=signup-start]')
        await page.fill('[data-attr=signup-name]', 'Alice Bob')
        await page.fill('[data-attr=signup-organization-name]', 'Hogflix SpinOff')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await page.click('[data-attr=signup-submit]')

        await expect(page).toHaveURL(/verify_email/)
    })

    // etc for multi-submission with generic email, social login, etc.
})
