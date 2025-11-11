import { expect, test } from '../utils/playwright-test-base'

const VALID_PASSWORD = 'hedgE-hog-123%'

test.describe('Signup', () => {
    test.beforeEach(async ({ page }) => {
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-item-logout]').click()
        await expect(page).toHaveURL(/.*\/login/)
        await page.goto('/signup')
    })

    test('Cannot create account with existing email', async ({ page }) => {
        await page.locator('[data-attr=signup-email]').fill('test@posthog.com')
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue('test@posthog.com')
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Jane Doe')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Jane Doe')
        await page.locator('[data-attr=signup-organization-name]').fill('Hogflix Movies')
        await expect(page.locator('[data-attr=signup-organization-name]')).toHaveValue('Hogflix Movies')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[data-attr=signup-submit]').click()

        await expect(page.locator('.LemonBanner')).toContainText('There is already an account with this email address.')
    })

    test('Cannot signup without required attributes', async ({ page }) => {
        await page.locator('[data-attr=signup-start]').click()

        await expect(page.getByText('Please enter your email to continue')).toBeVisible()
        await expect(page.getByText('Please enter your password to continue')).toBeVisible()
    })

    test('Cannot signup with invalid attributes', async ({ page }) => {
        await page.locator('[data-attr=password]').fill('123')
        await expect(page.locator('[data-attr=password]')).toHaveValue('123')
        await expect(page.locator('.text-danger')).not.toBeVisible()
        await page.locator('[data-attr=signup-start]').click()
        await expect(page.getByText('Please enter your email to continue')).toBeVisible()
        await expect(page.getByText('Add another word or two')).toBeVisible()

        await page.locator('[data-attr=password]').fill('123 abc def')
        await expect(page.getByText('Add another word or two')).not.toBeVisible()
    })

    test.skip('Can create user account with first name, last name and organization name', async ({ page }) => {
        let signupRequestBody: string | null = null

        await page.route('/api/signup/', async (route) => {
            signupRequestBody = route.request().postData()
            await route.continue()
        })

        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        await page.locator('[data-attr=signup-email]').fill(email)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(email)
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Alice Bob')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Alice Bob')
        await page.locator('[data-attr=signup-organization-name]').fill('Hogflix SpinOff')
        await expect(page.locator('[data-attr=signup-organization-name]')).toHaveValue('Hogflix SpinOff')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[data-attr=signup-submit]').click()

        const parsedBody = JSON.parse(signupRequestBody!)
        expect(parsedBody.first_name).toEqual('Alice')
        expect(parsedBody.last_name).toEqual('Bob')
        expect(parsedBody.organization_name).toEqual('Hogflix SpinOff')

        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    test('Can submit the signup form multiple times if there is a generic email set', async ({ page }) => {
        let signupRequestBody: string | null = null

        await page.route('/api/signup/', async (route) => {
            signupRequestBody = route.request().postData()
            await route.continue()
        })

        // Create initial account
        const email = `new_user+generic_error_test@posthog.com`
        await page.locator('[data-attr=signup-email]').fill(email)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(email)
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Alice Bob')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Alice Bob')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')

        // Wait for the signup request to complete
        const signupPromise = page.waitForResponse('/api/signup/')
        await page.locator('[data-attr=signup-submit]').click()
        await signupPromise

        const parsedBody = JSON.parse(signupRequestBody!)
        expect(parsedBody.first_name).toEqual('Alice')
        expect(parsedBody.last_name).toEqual('Bob')

        await page.goto('/signup')

        // Try to recreate account with same email- should fail
        await page.locator('[data-attr=signup-email]').fill(email)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(email)
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Alice Bob')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Alice Bob')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[data-attr=signup-submit]').click()

        await expect(page.locator('.LemonBanner')).toContainText('There is already an account with this email address.')

        await page.locator('[data-attr=signup-go-back]').click()

        // Update email to generic email
        const newEmail = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        await page.locator('[data-attr=signup-email]').fill('')
        await page.locator('[data-attr=signup-email]').fill(newEmail)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(newEmail)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[data-attr=signup-submit]').click()

        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    test('Can create user account with just a first name', async ({ page }) => {
        let signupRequestBody: string | null = null

        await page.route('/api/signup/', async (route) => {
            signupRequestBody = route.request().postData()
            await route.continue()
        })

        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        await page.locator('[data-attr=signup-email]').fill(email)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(email)
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Alice')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Alice')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')

        // Wait for the signup request to complete
        const signupPromise = page.waitForResponse('/api/signup/')
        await page.locator('[data-attr=signup-submit]').click()
        await signupPromise

        const parsedBody = JSON.parse(signupRequestBody!)
        expect(parsedBody.first_name).toEqual('Alice')
        expect(parsedBody.last_name).toBeUndefined()
        expect(parsedBody.organization_name).toBeUndefined()

        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    test('Can fill out all the fields on social login', async ({ page }) => {
        await page.goto('/logout')
        await expect(page).toHaveURL(/.*\/login/)
        await page.goto('/organization/confirm-creation?organization_name=&first_name=Test&email=test%40posthog.com')

        await expect(page.locator('[name=email]')).toHaveValue('test@posthog.com')
        await expect(page.locator('[name=first_name]')).toHaveValue('Test')
        await page.locator('[name=organization_name]').fill('Hogflix SpinOff')
        await expect(page.locator('[name=organization_name]')).toHaveValue('Hogflix SpinOff')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[type=submit]').click()
        await expect(page.locator('.Toastify [data-attr="error-toast"]')).toContainText(
            'Inactive social login session.'
        )
    })

    // TODO un-skip.
    // Skipping test as it was failing on master, see https://posthog.slack.com/archives/C0113360FFV/p1749742204672659
    test.skip('Shows redirect notice if redirecting for maintenance', async ({ page }) => {
        // Equivalent to setupFeatureFlags in Playwright
        await page.route('**/flags/*', async (route) => {
            const response = {
                config: {
                    enable_collect_everything: true,
                },
                featureFlags: {
                    'redirect-signups-to-instance': 'us',
                },
                isAuthenticated: false,
            }
            await route.fulfill({ json: response })
        })

        await page.goto('/logout')
        await expect(page).toHaveURL(/.*\/login/)

        // Modify window object before page load
        await page.goto('/signup?maintenanceRedirect=true')

        // Inject cloud = true into the context
        await page.evaluate(() => {
            const context = window['POSTHOG_APP_CONTEXT']
            if (context && context.preflight) {
                context.preflight.cloud = true
            }
        })

        await expect(page.locator('[data-attr="info-toast"]')).toContainText(
            `You've been redirected to signup on our US instance while we perform maintenance on our other instance.`
        )
    })

    test('Preserves next parameter through signup flow', async ({ page }) => {
        // Start signup with next parameter
        await page.goto('/signup?next=/custom_path')

        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        await page.locator('[data-attr=signup-email]').fill(email)
        await expect(page.locator('[data-attr=signup-email]')).toHaveValue(email)
        await page.locator('[data-attr=password]').fill(VALID_PASSWORD)
        await expect(page.locator('[data-attr=password]')).toHaveValue(VALID_PASSWORD)
        await page.locator('[data-attr=signup-start]').click()
        await page.locator('[data-attr=signup-name]').fill('Alice Bob')
        await expect(page.locator('[data-attr=signup-name]')).toHaveValue('Alice Bob')
        await page.locator('[data-attr=signup-organization-name]').fill('Hogflix SpinOff')
        await expect(page.locator('[data-attr=signup-organization-name]')).toHaveValue('Hogflix SpinOff')
        await page.locator('[data-attr=signup-role-at-organization]').click()
        await page.locator('.Popover li:first-child').click()
        await expect(page.locator('[data-attr=signup-role-at-organization]')).toContainText('Engineering')
        await page.locator('[data-attr=signup-submit]').click()

        // Verify we're redirected to verify_email page with next parameter preserved
        await expect(page).toHaveURL(/\/verify_email\/[a-zA-Z0-9_.-]*\?next=(\/|%2F)custom_path/)
    })
})
