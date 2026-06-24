import { Navigation } from '../../utils/navigation'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

let workspace: PlaywrightWorkspaceSetupResult | null = null

test.beforeAll(async ({ playwrightSetup }) => {
    workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
})

test.beforeEach(async ({ page, playwrightSetup }) => {
    await playwrightSetup.login(page, workspace!)
})

test('can open event explorer as an insight', async ({ page }) => {
    const navigation = new Navigation(page)
    await navigation.openHome()

    await navigation.openMenuItem('activity')
    await page.getByTestId('data-table-export-menu').click()
    await page.getByTestId('open-json-editor-button').click()

    await expect(page.getByTestId('insight-json-tab')).toHaveCount(1)
})

test('does not show the json tab usually', async ({ page }) => {
    const navigation = new Navigation(page)
    await navigation.openHome()

    await navigation.openMenuItem('product-analytics')

    await expect(page.getByTestId('insight-json-tab')).toHaveCount(0)
})
