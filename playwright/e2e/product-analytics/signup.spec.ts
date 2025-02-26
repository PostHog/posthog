import { AppContext } from '~/types'

import { mockFeatureFlags } from '../../utils/mockApi'
import { expect, test } from '../../utils/playwright-test-base'

const VALID_PASSWORD = 'hedgE-hog-123%'

test.describe('Signup', () => {
    test.beforeEach(async ({ page }) => {
        await page.click('[data-attr=menu-item-me]')
        await page.click('[data-attr=top-menu-item-logout]')
        await expect(page).toHaveURL(/\/login/)
        await page.goto('/signup')
    })

    test('cannot create account with existing email', async ({ page }) => {
        await page.fill('[data-attr=signup-email]', 'test@posthog.com')
        await page.fill('[data-attr=password]', VALID_PASSWORD)
        await page.click('[data-attr=signup-start]')
        await page.fill('[data-attr=signup-name]', 'Jane Doe')
        await page.fill('[data-attr=signup-organization-name]', 'Hogflix Movies')
        await page.click('[data-attr=signup-role-at-organization]')
        await page.click('.Popover li:first-child')
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.click('[data-attr=signup-submit]')

        await expect(page.locator('.LemonBanner')).toContainText('There is already an account with this email address.')
    })

    test('cannot signup without required attributes', async ({ page }) => {
        await page.click('[data-attr=signup-start]')
        await expect(page.locator('.text-danger:has-text("Please enter your email to continue")')).toBeVisible()
        await expect(page.locator('.text-danger:has-text("Please enter your password to continue")')).toBeVisible()
    })

    test('cannot signup with invalid attributes', async ({ page }) => {
        await page.fill('[data-attr=password]', '123')
        await expect(page.locator('.text-danger')).not.toBeVisible()
        await page.click('[data-attr=signup-start]')
        await expect(page.locator('.text-danger:has-text("Please enter your email to continue")')).toBeVisible()
        await expect(page.locator('.text-danger:has-text("Add another word or two")')).toBeVisible()

        await page.fill('[data-attr=password]', '123 abc def')
        await expect(page.locator('.text-danger:has-text("Add another word or two")')).not.toBeVisible()
    })

    test('can create user account with first name, last name and organization name', async ({ page }) => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        let signupRequestBody: string | null = null

        await page.route('/api/signup/', async (route) => {
            signupRequestBody = route.request().postData()
            await route.continue()
        })

        await page.fill('[data-attr=signup-email]', email)
        await page.fill('[data-attr=password]', VALID_PASSWORD)
        await page.click('[data-attr=signup-start]')
        await page.fill('[data-attr=signup-name]', 'Alice Bob')
        await page.fill('[data-attr=signup-organization-name]', 'Hogflix SpinOff')
        await page.click('[data-attr=signup-role-at-organization]')
        await page.click('.Popover li:first-child')
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.click('[data-attr=signup-submit]')

        const parsedBody = JSON.parse(signupRequestBody!)
        expect(parsedBody.first_name).toBe('Alice')
        expect(parsedBody.last_name).toBe('Bob')
        expect(parsedBody.organization_name).toBe('Hogflix SpinOff')

        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    test('can create user account with just a first name', async ({ page }) => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        let signupRequestBody: string | null = null

        await page.route('/api/signup/', async (route) => {
            signupRequestBody = route.request().postData()
            await route.continue()
        })

        await page.fill('[data-attr=signup-email]', email)
        await page.fill('[data-attr=password]', VALID_PASSWORD)
        await page.click('[data-attr=signup-start]')
        await page.fill('[data-attr=signup-name]', 'Alice')
        await page.click('[data-attr=signup-role-at-organization]')
        await page.click('.Popover li:first-child')
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.click('[data-attr=signup-submit]')

        const parsedBody = JSON.parse(signupRequestBody!)
        expect(parsedBody.first_name).toBe('Alice')
        expect(parsedBody.last_name).toBeUndefined()
        expect(parsedBody.organization_name).toBeUndefined()

        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    test('can fill out all the fields on social login', async ({ page }) => {
        await page.goto('/logout')
        await expect(page).toHaveURL(/\/login/)
        await page.goto('/organization/confirm-creation?organization_name=&first_name=Test&email=test%40posthog.com')

        await expect(page.locator('[name=email]')).toHaveValue('test@posthog.com')
        await expect(page.locator('[name=first_name]')).toHaveValue('Test')
        await page.fill('[name=organization_name]', 'Hogflix SpinOff')
        await page.click('[data-attr=signup-role-at-organization]')
        await page.click('.Popover li:first-child')
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.click('[type=submit]')
        await expect(page.locator('.Toastify [data-attr="error-toast"]')).toContainText(
            'Inactive social login session.'
        )
    })

    test('shows redirect notice if redirecting for maintenance', async ({ page }) => {
        await mockFeatureFlags(page, {
            'redirect-signups-to-instance': 'us',
        })

        // Set up the window context before navigation
        await page.addInitScript(() => {
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                preflight: {
                    ...(window.POSTHOG_APP_CONTEXT?.preflight as AppContext['preflight']),
                    cloud: true,
                },
            } as AppContext
        })

        await page.goto('/logout')
        await expect(page).toHaveURL(/\/login/)
        await page.goto('/signup?maintenanceRedirect=true')

        await expect(page.locator('[data-attr="info-toast"]')).toContainText(
            `You've been redirected to signup on our US instance while we perform maintenance on our other instance.`
        )
    })
})
