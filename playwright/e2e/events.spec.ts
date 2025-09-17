import path from 'path'

import { expect, test } from '../utils/playwright-test-base'

test.describe('Events', () => {
    test.beforeEach(async ({ page }) => {
        await page.route('/api/event/values?key=%24browser', (route) =>
            route.fulfill({
                status: 200,
                body: JSON.stringify([{ name: '96' }, { name: '97' }]),
            })
        )

        await page.route('/api/projects/@current/property_definitions/?limit=5000', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/property_definitions.json'),
            })
        )

        await page.route('/api/projects/*/property_definitions?is_feature_flag=false&search=&*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/property_definitions.json'),
            })
        )

        await page.route('/api/projects/*/property_definitions?is_feature_flag=false&search=%24time*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/only_time_property_definition.json'),
            })
        )

        await page.route('/api/projects/*/property_definitions?is_feature_flag=false&search=%24browser*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/only_browser_version_property_definition.json'),
            })
        )

        await page.route('/api/projects/*/property_definitions?is_feature_flag=true*', (route) =>
            route.fulfill({
                status: 200,
                path: path.resolve(__dirname, '../mocks/events/feature_flag_property_definition.json'),
            })
        )

        await page.route('/api/event/values/?key=$browser_version', (route) =>
            route.fulfill({
                status: 200,
                body: JSON.stringify([{ name: '96' }, { name: '97' }]),
            })
        )

        await page.goToMenuItem('activity')
        await page.waitForURL('**/activity/explore')
    })

    test.skip('Apply 1 overall filter', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').click()
        await page.locator('.taxonomic-list-row').getByText('Browser').first().click()
        await page.locator('[data-attr=prop-val]').click({ force: true })
        await page.waitForResponse('/api/event/values?key=%24browser')
        await page.locator('[data-attr=prop-val-0]').click()
        await expect(page.locator('.DataTable')).toBeVisible()
    })

    test.skip('Separates feature flag properties into their own tab', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await expect(page.locator('[data-attr="taxonomic-tab-event_feature_flags"]')).toContainText('Feature flags: 2')
        await page.locator('[data-attr="taxonomic-tab-event_feature_flags"]').click()
        await expect(page.locator('.taxonomic-list-row:visible')).toHaveCount(2)
    })
})
