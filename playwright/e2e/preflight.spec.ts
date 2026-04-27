import { expect, test } from '../utils/playwright-test-base'

const preflightSuccessResponse = {
    django: true,
    redis: true,
    plugins: true,
    celery: true,
    clickhouse: true,
    kafka: true,
    db: true,
    initiated: true,
    cloud: false,
    demo: false,
    realm: 'hosted-clickhouse',
    region: null,
    available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false },
    can_create_org: true,
    email_service_available: true,
    slack_service: { available: false, client_id: null },
    object_storage: true,
}

test.describe('Preflight', () => {
    test('Preflight experimentation', async ({ page }) => {
        await page.route(/_preflight/, async (route) => {
            await route.fulfill({ json: preflightSuccessResponse })
        })

        await page.goto('/logout')
        await page.goto('/preflight')

        await page.locator('[data-attr=preflight-experimentation]').click()

        await expect(page.locator('[data-attr=preflight-refresh]')).toBeVisible()
        // expand rows
        await page.locator('.Preflight__check-summary .LemonButton').click()
        await expect(page.locator('.PreflightItem [data-attr=caption]')).toContainText(
            'Not required for experimentation mode'
        )
        await expect(page.locator('[data-attr=preflight-complete]')).toBeVisible()
        await page.locator('[data-attr=preflight-complete]').click()
        await expect(page).toHaveURL(/.*\/signup/)
    })

    test('Preflight live mode', async ({ page }) => {
        await page.route(/_preflight/, async (route) => {
            await route.fulfill({ json: preflightSuccessResponse })
        })

        await page.goto('/logout')
        await page.goto('/preflight')

        await page.locator('[data-attr=preflight-live]').click()
        await expect(page.locator('.PreflightItem')).toHaveCount(10)
        await expect(page.locator('[data-attr="status-text"]:has-text("Validated")')).toHaveCount(9)
        await expect(page.locator('[data-attr="status-text"]:has-text("Warning")')).toHaveCount(1)
        await expect(page.locator('.PreflightItem [data-attr=caption]')).toContainText(
            'Set up before ingesting real user data'
        )
        await expect(page.locator('[data-attr=preflight-complete]')).toBeVisible()
    })

    test('Preflight can have errors too', async ({ page }) => {
        await page.route(/_preflight/, async (route) => {
            await route.fulfill({ json: { ...preflightSuccessResponse, celery: false } })
        })

        await page.goto('/logout')
        await page.goto('/preflight')

        await page.locator('[data-attr=preflight-live]').click()
        await expect(page.locator('.PreflightItem')).toHaveCount(10)
        await expect(page.locator('[data-attr="status-text"]:has-text("Validated")')).toHaveCount(8)
        await expect(page.locator('[data-attr="status-text"]:has-text("Warning")')).toHaveCount(1)
        await expect(page.locator('[data-attr="status-text"]:has-text("Error")')).toHaveCount(1)
        await expect(page.locator('.PreflightItem [data-attr=caption]')).toContainText(
            'Set up before ingesting real user data'
        )
        await expect(page.locator('[data-attr=preflight-complete]')).not.toBeVisible()
        await expect(
            page.locator(
                '.Preflight__cannot-continue:has-text("All required checks must pass before you can continue")'
            )
        ).toHaveCount(1)
    })
})
