import { LoginPage } from '../page-models/loginPage'
import { LOGIN_PASSWORD, LOGIN_USERNAME } from '../utils/playwright-test-core'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Auth', () => {
    let loginPage: LoginPage
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await page.locator('[data-attr=new-account-menu-button]').click()
        loginPage = new LoginPage(page)
    })

    test('Logout', async ({ page }) => {
        await page.locator('[data-attr=new-account-menu-logout-button]').click()
        await expect(page).toHaveURL('/login')
    })

    test('Logout and login', async ({ page }) => {
        await page.locator('[data-attr=new-account-menu-logout-button]').click()

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
        // available_social_auth_providers comes from POSTHOG_APP_CONTEXT, which is server-rendered into the
        // login page HTML and read directly by preflightLogic on mount — so API mocks don't apply. Patch the
        // context before the page scripts run; mutating it after the page has loaded is racy and only
        // renders the button on lucky timing.
        await page.addInitScript(() => {
            let _context: any = undefined
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    if (_context?.preflight) {
                        _context.preflight.available_social_auth_providers ??= {}
                        _context.preflight.available_social_auth_providers['google-oauth2'] = true
                    }
                    return _context
                },
                set(value) {
                    _context = value
                },
                configurable: true,
            })
        })

        await page.locator('[data-attr=new-account-menu-logout-button]').click()

        await expect(page.locator('a[href="/login/google-oauth2/"]')).toBeVisible()
    })

    test('Try logging in improperly and then properly', async ({ page }) => {
        await page.locator('[data-attr=new-account-menu-logout-button]').click()

        await loginPage.enterUsername(LOGIN_USERNAME)
        await expect(page.locator('[data-attr=login-email]')).toHaveValue(LOGIN_USERNAME)

        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword('wrong password')
        await expect(page.locator('[data-attr=password]')).toHaveValue('wrong password')

        await loginPage.clickLogin()
        // Scope to the error banner: on cloud a separate info banner (OtherRegionHint) also renders here.
        await expect(page.locator('.LemonBanner--error')).toContainText('Invalid email or password.')

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await loginPage.clickLogin()

        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Redirect to appropriate place after login', async ({ page, context }) => {
        await context.clearCookies()
        await page.goto('/activity/explore', { waitUntil: 'commit' })
        await expect(page).toHaveURL(/\/login/)

        await loginPage.enterUsername(LOGIN_USERNAME)
        await page.locator('[data-attr=login-email]').blur()
        await page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })

        await loginPage.enterPassword(LOGIN_PASSWORD)
        await loginPage.clickLogin()

        await expect(page).toHaveURL(/\/activity\/explore/)
    })

    test('Redirect to appropriate place after login with complex URL', async ({ page, context }) => {
        await context.clearCookies()
        await page.goto('/insights?search=testString', { waitUntil: 'commit' })
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
        await page.goto('/signup')
        await expect(page).toHaveURL(/\/project\/\d+/)
    })

    test('Logout in another tab results in logout in the current tab too', async ({ page, context }) => {
        const secondPage = await context.newPage()
        await secondPage.goto('/')
        await secondPage.locator('[data-attr=new-account-menu-button]').waitFor({ state: 'visible', timeout: 30000 })
        await secondPage.locator('[data-attr=new-account-menu-button]').click()
        await secondPage.locator('[data-attr=new-account-menu-logout-button]').click()
        await secondPage.waitForURL(/\/login/)

        // Reload the page to trigger API calls that will detect the logout
        await page.reload()
        await page.waitForURL(/\/login/, { timeout: 30000 })
    })
})
