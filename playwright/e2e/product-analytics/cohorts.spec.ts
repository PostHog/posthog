import { CohortPage } from '../../page-models/cohortPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Cohorts', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeEach(async ({ page, playwrightSetup }) => {
        // Dedicated empty workspace per test — no shared demo team, so the cohorts list
        // only ever contains what this test creates.
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)

        await page.goToMenuItem('people')
        await page.goToMenuItem('cohorts')

        await expect(page).toHaveTitle('Cohorts • PostHog')
        await expect(page.locator('[data-attr="create-cohort"]')).toBeVisible()
        await expect(page.locator('[data-attr="product-introduction-docs-link"]')).toHaveText(/Learn more/)
    })

    test('Can create a cohort', async ({ page }) => {
        const name = randomString('Test-Cohort-')

        await new CohortPage(page).createCohort(name)

        await page.goToMenuItem('people')
        await page.goToMenuItem('cohorts')

        await expect(page.locator('tbody')).toContainText(name)
    })

    test('Duplicate a cohort', async ({ page }) => {
        // Cohort calculation has to settle twice before the next duplicate item flips enabled.
        test.setTimeout(120_000)

        const name = randomString('Test-Cohort-')

        await new CohortPage(page).createCohort(name)

        await page.goToMenuItem('people')
        await page.goToMenuItem('cohorts')

        await page.click('tbody >> text=' + name)
        await expect(page.locator('[data-attr="scene-name"]')).toContainText(name)

        // Open the panel once, then just wait for each item to flip enabled
        await page.locator('[data-attr=open-context-panel-button]').first().click()

        const dynamicItem = page.getByRole('button', { name: 'Duplicate as dynamic cohort' })
        await expect(dynamicItem).toBeEnabled({ timeout: 30_000 })
        await dynamicItem.click()
        await page.locator('.Toastify__toast-body').getByRole('button', { name: 'View cohort' }).click()

        // The panel's open state persists across the client-side nav. The open
        // button is unmounted while the panel is open, so only click it if the
        // panel actually closed. Wait for the URL to advance to the new cohort
        // before checking visibility.
        await page.waitForURL(/\/cohorts\/\d+/)
        const reopenPanelButton = page.locator('[data-attr=open-context-panel-button]').first()
        if (await reopenPanelButton.isVisible().catch(() => false)) {
            await reopenPanelButton.click()
        }

        const staticItem = page.getByRole('button', { name: 'Duplicate as static cohort' })
        await expect(staticItem).toBeEnabled({ timeout: 30_000 })
        await staticItem.click()
        await page.locator('.Toastify__toast-body').getByRole('button', { name: 'View cohort' }).click()

        // Wait until we've actually landed on the static-copy page before deleting —
        // otherwise cohort-delete fires on the still-mounted dynamic-copy page and the
        // static copy survives the deletion.
        await expect(page.locator('[data-attr="scene-name"]')).toContainText(name + ' (dynamic copy) (static copy)')

        await page.locator('[data-attr="cohort-delete"]').click()
        const deleteDialog = page.locator('.LemonModal__layout').filter({ hasText: 'Delete cohort?' })
        await expect(deleteDialog).toBeVisible()
        await deleteDialog.getByRole('button', { name: 'Delete' }).click()

        // The delete redirects back to the cohorts list (e.g. /cohorts?page=1#panel=max)
        // once the request resolves, so waiting for it guarantees the deletion committed
        // before we reload and assert. Match the list URL but not the /cohorts/<id> detail.
        await expect(page).toHaveURL(/\/cohorts(\?|#|$)/)

        await page.goToMenuItem('people')
        await page.goToMenuItem('cohorts')

        await expect(page.locator('tbody')).not.toContainText(name + ' (dynamic copy) (static copy)')
    })
})
