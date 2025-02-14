import { expect, LOGIN_PASSWORD, LOGIN_USERNAME, test } from '../utils/playwright-test-base'

test.describe('Auth', () => {
    test.beforeEach(async ({ page }) => {
        await page.locator('[data-attr=menu-item-me]').click()
    })

    test('Logout', async ({ page }) => {
        await page.locator('[data-attr=top-menu-item-logout]').click()
        await expect(page).toHaveURL('/login')
    })

    test('Logout and login', async ({ page }) => {
        await page.locator('[data-attr=top-menu-item-logout]').click()

        await page.locator('[data-attr=login-email]').fill(LOGIN_USERNAME)
        await expect(page.locator('[data-attr=login-email]')).toHaveValue(LOGIN_USERNAME)

        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await page.locator('[data-attr=password]').fill(LOGIN_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(LOGIN_PASSWORD)

        await page.locator('[type=submit]').click()
        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Logout and verify Google login button has correct link', async ({ page }) => {
        await page.locator('[data-attr=top-menu-item-logout]').click()

        await page.evaluate(() => {
            window.POSTHOG_APP_CONTEXT.preflight.available_social_auth_providers = {
                'google-oauth2': true,
            }
        })

        await expect(page.locator('a[href="/login/google-oauth2/"]')).toBeVisible()
    })

    test('Try logging in improperly and then properly', async ({ page }) => {
        await page.locator('[data-attr=top-menu-item-logout]').click()

        await page.locator('[data-attr=login-email]').fill(LOGIN_USERNAME)
        await expect(page.locator('[data-attr=login-email]')).toHaveValue(LOGIN_USERNAME)

        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await page.locator('[data-attr=password]').fill('wrong password')
        await expect(page.locator('[data-attr=password]')).toHaveValue('wrong password')

        await page.locator('[type=submit]').click()
        await expect(page.locator('.LemonBanner')).toContainText('Invalid email or password.')

        await page.locator('[data-attr=password]').fill(LOGIN_PASSWORD)
        await page.locator('[type=submit]').click()

        await expect(page).toHaveURL('/')
    })

    test('Redirect to appropriate place after login', async ({ page }) => {
        await page.goto('/logout')
        await expect(page).toHaveURL(/\/login/)

        await page.goto('/activity/explore')
        await expect(page).toHaveURL(/\/login/)

        await page.locator('[data-attr=login-email]').fill(LOGIN_USERNAME)
        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await page.locator('[data-attr=password]').fill(LOGIN_PASSWORD)
        await page.locator('[type=submit]').click()

        await expect(page).toHaveURL(/\/activity\/explore/)
    })

    test('Redirect to appropriate place after login with complex URL', async ({ page }) => {
        await page.goto('/logout')
        await expect(page).toHaveURL(/\/login/)

        await page.goto('/insights?search=testString')
        await expect(page).toHaveURL(/\/login/)

        await page.locator('[data-attr=login-email]').fill(LOGIN_USERNAME)
        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await page.locator('[data-attr=password]').fill(LOGIN_PASSWORD)
        await page.locator('[type=submit]').click()

        await expect(page).toHaveURL(/search%3DtestString/)
        await expect(page.locator('.saved-insight-empty-state')).toContainText('testString')
    })

    test('Cannot access signup page if authenticated', async ({ page }) => {
        await page.goto('/signup')
        await expect(page).toHaveURL('/project/1')
    })

    test('Logout in another tab results in logout in the current tab too', async ({ page, context }) => {
        // Perform logout in a new context (simulating another tab)
        const secondContext = await context.newContext()
        const secondPage = await secondContext.newPage()
        await secondPage.goto('/logout')

        // Now interact with the original page
        await page.locator('[data-attr=menu-item-me]').click()
        await expect(page).toHaveURL('/login') // Should be redirected
    })
})
