import path from 'path'

import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Events', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)

        await page.route('/api/event/values?key=%24browser', (route) =>
            route.fulfill({
                status: 200,
                body: JSON.stringify([{ name: 'Chrome 145' }, { name: 'Firefox' }]),
            })
        )

        await page.route('/api/projects/@current/property_definitions/?limit=5000', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/property_definitions.json'),
            })
        )

        // The endpoint injects params (exclude_hidden, exclude_restricted, ...) between
        // is_feature_flag and search, so match on the discriminating params regardless of order.
        await page.route('**/property_definitions?*is_feature_flag=false*search=&*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/property_definitions.json'),
            })
        )

        await page.route('**/property_definitions?*is_feature_flag=false*search=%24time*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/only_time_property_definition.json'),
            })
        )

        await page.route('**/property_definitions?*is_feature_flag=false*search=%24browser*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/browser_property_definitions.json'),
            })
        )

        await page.route('**/property_definitions?*is_feature_flag=true*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/feature_flag_property_definition.json'),
            })
        )

        await page.goToMenuItem('activity')
        await page.waitForURL('**/activity/explore')
    })

    test('Apply a single overall filter', async ({ page }) => {
        await page.locator('[data-attr^="new-prop-filter-EventPropertyFilters."]').first().click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').fill('$browser')
        await page.locator('.taxonomic-list-row').getByText('Browser').first().click()
        await page.locator('[data-attr=prop-val]').click({ force: true })
        await page.waitForResponse('/api/event/values?key=%24browser')

        const taxonomicValueInput = page.locator('[data-attr="taxonomic-value-select"] input')
        await expect(taxonomicValueInput).toBeVisible()
        await taxonomicValueInput.fill('Chrome 145')
        await taxonomicValueInput.press('Enter')
        await expect(page.locator('.DataTable')).toBeVisible()
    })

    test('Separates feature flag properties into their own tab', async ({ page }) => {
        await page.locator('[data-attr^="new-prop-filter-EventPropertyFilters."]').first().click()
        await expect(page.locator('[data-attr="taxonomic-tab-event_feature_flags"]')).toContainText('Feature flags: 2')
        await page.locator('[data-attr="taxonomic-tab-event_feature_flags"]').click()
        await expect(page.locator('.taxonomic-list-row:visible')).toHaveCount(2)
    })
})
