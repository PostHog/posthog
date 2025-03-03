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

    /** works locally but not in CI - in CI the event list is never loading */
    test.skip('Click on an event', async ({ page }) => {
        await expect(page.locator('.DataTable .DataTable__row').first()).toBeVisible()
        await page.locator('.DataTable .DataTable__row .LemonTable__toggle').first().click()
        await expect(page.locator('[data-attr=event-details]')).toBeVisible()
    })

    test('Apply 1 overall filter', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').click()
        await page.locator('.taxonomic-list-row').getByText('Browser').first().click()
        await page.locator('[data-attr=prop-val]').click({ force: true })
        await page.waitForResponse('/api/event/values?key=%24browser')
        await page.locator('[data-attr=prop-val-0]').click()
        await expect(page.locator('.DataTable')).toBeVisible()
    })

    test('Separates feature flag properties into their own tab', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await expect(page.locator('[data-attr="taxonomic-tab-event_feature_flags"]')).toContainText('Feature flags: 2')
        await page.locator('[data-attr="taxonomic-tab-event_feature_flags"]').click()
        await expect(page.locator('.taxonomic-list-row:visible')).toHaveCount(2)
    })

    test('Use before and after with a DateTime property', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').type('$time')
        await expect(page.locator('.taxonomic-list-row')).toHaveCount(2)
        await page.locator('[data-attr=prop-filter-event_properties-0]').click({ force: true })

        await page.locator('[data-attr="taxonomic-operator"]').click()
        await expect(page.getByRole('menuitem', { name: '> after' })).toBeVisible()
        await expect(page.getByRole('menuitem', { name: '< before' })).toBeVisible()
    })

    test('Use less than and greater than with a numeric property', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        await expect(page.locator('.taxonomic-list-row')).toHaveCount(1)
        await page.locator('.taxonomic-list-row').click()

        await page.locator('[data-attr="taxonomic-operator"]').click()
        await expect(page.locator('.operator-value-option')).toHaveCount(9) // 8 + 1 for the label in the LemonSelect button
        await expect(page.getByRole('menuitem', { name: '< less than' })).toBeVisible()
        await expect(page.getByRole('menuitem', { name: '> greater than' })).toBeVisible()
    })

    test('Adds and removes an additional column', async ({ page }) => {
        await page.locator('[data-attr=events-table-column-selector]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        await expect(page.locator('.taxonomic-list-row')).toHaveCount(1)
        await page.locator('.taxonomic-list-row').click()
        await expect(page.locator('.SelectedColumn')).toHaveCount(7)
        await page.locator('[data-attr=column-display-item-remove-icon]').last().click()
        await expect(page.locator('.SelectedColumn')).toHaveCount(6)
    })

    test('Keeps the popup open after selecting an option', async ({ page }) => {
        await page.locator('[data-attr="new-prop-filter-EventPropertyFilters.0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').type('$browser_version')
        await expect(page.locator('.taxonomic-list-row')).toHaveCount(1)
        await page.locator('.taxonomic-list-row').click()

        await page.locator('[data-attr="taxonomic-operator"]').click()
        await page.getByRole('menuitem', { name: '> greater than' }).click()
        await expect(page.locator('[data-attr="taxonomic-operator"]')).toBeVisible()
    })
})
