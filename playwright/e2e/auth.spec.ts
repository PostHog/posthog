import { Page } from '@playwright/test'

import { PreflightStatus } from '~/types'

import { LoginPage } from '../page-models/loginPage'
import { LOGIN_PASSWORD, LOGIN_USERNAME, expect, test } from '../utils/playwright-test-core'

// Auth tests manage their own login state — clear storageState so we start unauthenticated
test.use({ storageState: { cookies: [], origins: [] } })

async function loginViaAPI(page: Page): Promise<void> {
    await page.request.post('/api/login/', {
        data: { email: LOGIN_USERNAME, password: LOGIN_PASSWORD },
    })
}

test.describe('Auth', () => {
    let loginPage: LoginPage
    test.beforeEach(async ({ page }) => {
        loginPage = new LoginPage(page)
    })

    test('Logout', async ({ page }) => {
        await loginViaAPI(page)
        await page.goto('/')
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-item-logout]').click()
        await expect(page).toHaveURL('/login')
    })

    test('Logout and login', async ({ page }) => {
        await page.goto('/login')

        await loginPage.enterUsername(LOGIN_USERNAME)
        await expect(page.locator('[data-attr=login-email]')).toHaveValue(LOGIN_USERNAME)

        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(LOGIN_PASSWORD)

        await loginPage.clickLogin()
        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Logout and verify Google login button has correct link', async ({ page }) => {
        await page.goto('/login')

        await page.setAppContext('preflight', {
            available_social_auth_providers: {
                'google-oauth2': true,
            },
        } as Partial<PreflightStatus> as PreflightStatus)

        await expect(page.locator('a[href="/login/google-oauth2/"]')).toBeVisible()
    })

    test('Try logging in improperly and then properly', async ({ page }) => {
        await page.goto('/login')

        await loginPage.enterUsername(LOGIN_USERNAME)
        await expect(page.locator('[data-attr=login-email]')).toHaveValue(LOGIN_USERNAME)

        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword('wrong password')
        await expect(page.locator('[data-attr=password]')).toHaveValue('wrong password')

        await loginPage.clickLogin()
        await expect(page.locator('.LemonBanner')).toContainText('Invalid email or password.')

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await loginPage.clickLogin()

        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Redirect to appropriate place after login', async ({ page }) => {
        await page.goto('/activity/explore')
        await expect(page).toHaveURL(/\/login/)

        await loginPage.enterUsername(LOGIN_USERNAME)
        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await loginPage.clickLogin()

        await expect(page).toHaveURL(/\/activity\/explore/)
    })

    test('Redirect to appropriate place after login with complex URL', async ({ page }) => {
        await page.goto('/insights?search=testString')
        await expect(page).toHaveURL(/\/login/)

        await loginPage.enterUsername(LOGIN_USERNAME)
        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await loginPage.clickLogin()

        await expect(page).toHaveURL(/search%3DtestString/)
        await expect(page.locator('.saved-insight-empty-state')).toContainText('testString')
    })

    test('Cannot access signup page if authenticated', async ({ page }) => {
        await loginViaAPI(page)
        await page.goto('/signup')
        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Logout in another tab results in logout in the current tab too', async ({ page, context }) => {
        await loginViaAPI(page)
        await page.goto('/')

        const secondPage = await context.newPage()
        await secondPage.goto('/logout')
        await secondPage.waitForURL(/\/login/)

        await page.reload()
        await page.waitForURL(/\/login/, { timeout: 30000 })
    })
})
