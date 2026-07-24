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
})
