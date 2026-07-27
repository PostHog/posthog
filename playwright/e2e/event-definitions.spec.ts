import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Event Definitions', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    // Keep demo data: the test reads an existing event definition row and opens its recordings.
    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('See recordings action', async ({ page }) => {
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('event-definitions')

        // default tab is events
        await page.waitForSelector('tbody tr:has-text("Loading… Loading… Loading…")', { state: 'detached' })

        await expect(page.locator('tbody tr .LemonButton').first()).toBeVisible()
        await expect(page.locator('[data-attr=events-definition-table]')).toBeVisible()

        const eventName = await page.locator('tbody tr .PropertyKeyInfo__text').first().innerText()

        await expect(page.locator('[data-attr=event-definitions-table-view-recordings]').first()).toBeVisible()
        // View recordings opens the replay page in a new browser tab
        const popupPromise = page.context().waitForEvent('page')
        await page.locator('[data-attr=event-definitions-table-view-recordings]').first().click()
        const replayTab = await popupPromise
        await expect(replayTab).toHaveURL(/replay/)

        await replayTab.locator('.LemonButton--has-icon .LemonButton__content').filter({ hasText: 'Filters' }).click()

        await expect(replayTab.locator('.UniversalFilterButton').first()).toContainText(eventName, {
            ignoreCase: true,
        })
    })
})
