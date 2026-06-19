import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Toolbar', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Toolbar loads', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()

        const loc = await page.evaluate(() => window.location)
        await page.locator('[data-attr="url-input"]').fill(`http://${loc.host}/demo`)
        await page.locator('[data-attr="url-save"]').click()

        const href = await page.locator('[data-attr="toolbar-open"]').first().getAttribute('href')
        if (href) {
            await page.goto(href)
        }

        await expect(page.locator('#__POSTHOG_TOOLBAR__ .Toolbar')).toBeVisible({ timeout: 5000 })
    })

    test('Toolbar item in sidebar has launch options', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()
        await expect(page).toHaveURL(/.*\/toolbar/)
    })

    test('Can open add authorized URL form', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.locator('[data-attr="toolbar-add-url"]').click()
        await expect(page.locator('[data-attr="url-input"]')).toBeVisible()
    })
})
