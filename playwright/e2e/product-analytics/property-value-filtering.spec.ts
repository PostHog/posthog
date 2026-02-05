import { expect, test } from '../../utils/workspace-test-base'

test.describe('Property value filtering', () => {
    test('Keeps suggested values at top when search results arrive', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
        await playwrightSetup.login(page, workspace)

        // Mock initial suggested values (loaded when input is focused with no search)
        await page.route('**/api/event/values?key=browser_name**', (route) => {
            const url = new URL(route.request().url())
            const searchValue = url.searchParams.get('value')

            if (!searchValue) {
                // Initial load - return suggested values
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([{ name: 'Val One' }, { name: 'Val Two' }, { name: 'Val Three' }]),
                })
            } else if (searchValue === 'one') {
                // Search for "one" - return results that include the suggested value
                // but with new values first (simulating API behavior)
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([
                        { name: 'This One' },
                        { name: 'That One' },
                        { name: 'Some One' },
                        { name: 'Val One' },
                    ]),
                })
            } else {
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([]),
                })
            }
        })

        // Navigate to insights
        await page.goto(`/project/${workspace!.team_id}/insights/new`)
        await expect(page.getByTestId('insights-graph')).toBeVisible()

        // Add a property filter
        await test.step('Add property filter', async () => {
            await page.getByRole('button', { name: 'Add filter group' }).click()
            await page.getByRole('button', { name: 'Filter', exact: true }).click()

            // Search for and select browser_name property
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('browser_name')
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('Verify initial suggested values load', async () => {
            // Click on property value input
            const propertyValueInput = page.getByTestId('prop-val')
            await propertyValueInput.click()

            // Wait for initial values to load
            await page.waitForResponse('**/api/event/values?key=browser_name**')

            // Verify suggested values appear
            await expect(page.getByText('Val One')).toBeVisible()
            await expect(page.getByText('Val Two')).toBeVisible()
            await expect(page.getByText('Val Three')).toBeVisible()
        })

        await test.step('Type search and verify suggested value stays at top in original order', async () => {
            const propertyValueInput = page.getByTestId('prop-val')

            // Type "one" to trigger search
            await propertyValueInput.fill('one')

            // LemonInputSelect should immediately filter client-side to show only "Val One"
            // Wait a bit for client-side filtering
            await page.waitForTimeout(100)

            // Verify "Val One" is still visible (client-side filtered)
            await expect(page.getByText('Val One')).toBeVisible()

            // Wait for the API call to complete
            await page.waitForResponse((response) => {
                const url = new URL(response.url())
                return url.pathname.includes('/api/event/values') && url.searchParams.get('value') === 'one'
            })

            // Wait for results to render
            await page.waitForTimeout(500)

            // Verify all matching options are now visible
            await expect(page.getByText('This One')).toBeVisible()
            await expect(page.getByText('That One')).toBeVisible()
            await expect(page.getByText('Some One')).toBeVisible()
            await expect(page.getByText('Val One')).toBeVisible()

            // Verify "Val One" appears FIRST (before "This One")
            // This verifies that suggested values stay at the top
            const options = page.locator('[data-attr^="prop-val-"]')
            const firstOption = options.first()
            await expect(firstOption).toContainText('Val One')

            // Verify "Val One" has the suggested icon
            const valOneOption = page.locator('[data-attr^="prop-val-"]').first()
            await expect(valOneOption.locator('svg')).toBeVisible()
        })

        await test.step('Verify suggested value can be clicked without list shifting', async () => {
            // At this point, "Val One" should be at the top and stable
            // User should be able to click it without the list shifting
            const valOneOption = page.locator('[data-attr^="prop-val-"]').first()
            await expect(valOneOption).toContainText('Val One')

            // Click it
            await valOneOption.click()

            // Verify it was selected (input should be hidden or have the value)
            const selectedValue = page.locator('.LemonSnack').filter({ hasText: 'Val One' })
            await expect(selectedValue).toBeVisible()
        })
    })

    test('Multiple suggested values maintain original order', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
        await playwrightSetup.login(page, workspace)

        // Mock with multiple matching suggested values
        await page.route('**/api/event/values?key=browser_name**', (route) => {
            const url = new URL(route.request().url())
            const searchValue = url.searchParams.get('value')

            if (!searchValue) {
                // Initial load - return suggested values in specific order
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([{ name: 'First Value' }, { name: 'Second Value' }, { name: 'Third Value' }]),
                })
            } else if (searchValue === 'value') {
                // Search for "value" - return results with suggested values in different order
                // API returns them reversed + new values, but we should show in original order
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([
                        { name: 'New Value 1' },
                        { name: 'Third Value' },
                        { name: 'New Value 2' },
                        { name: 'Second Value' },
                        { name: 'First Value' },
                    ]),
                })
            } else {
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([]),
                })
            }
        })

        // Navigate to insights and add property filter
        await page.goto(`/project/${workspace!.team_id}/insights/new`)
        await expect(page.getByTestId('insights-graph')).toBeVisible()

        await page.getByRole('button', { name: 'Add filter group' }).click()
        await page.getByRole('button', { name: 'Filter', exact: true }).click()

        const searchField = page.getByTestId('taxonomic-filter-searchfield')
        await searchField.waitFor({ state: 'visible' })
        await searchField.fill('browser_name')
        await page.locator('.taxonomic-list-row').first().click()

        // Click on property value input and wait for initial load
        const propertyValueInput = page.getByTestId('prop-val')
        await propertyValueInput.click()
        await page.waitForResponse('**/api/event/values?key=browser_name**')

        // Type "value" to trigger search
        await propertyValueInput.fill('value')
        await page.waitForResponse((response) => {
            const url = new URL(response.url())
            return url.pathname.includes('/api/event/values') && url.searchParams.get('value') === 'value'
        })
        await page.waitForTimeout(500)

        // Verify the order: suggested values first in ORIGINAL order, then new values
        const options = page.locator('[data-attr^="prop-val-"]')
        await expect(options.nth(0)).toContainText('First Value')
        await expect(options.nth(1)).toContainText('Second Value')
        await expect(options.nth(2)).toContainText('Third Value')
        await expect(options.nth(3)).toContainText('New Value 1')
        await expect(options.nth(4)).toContainText('New Value 2')

        // Verify all suggested values have the icon
        await expect(options.nth(0).locator('svg')).toBeVisible()
        await expect(options.nth(1).locator('svg')).toBeVisible()
        await expect(options.nth(2).locator('svg')).toBeVisible()
        await expect(options.nth(3).locator('svg')).not.toBeVisible()
        await expect(options.nth(4).locator('svg')).not.toBeVisible()
    })

    test('Suggested values persist even when API does not return them', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
        await playwrightSetup.login(page, workspace)

        // Mock with 6 initial suggested values, but API only returns 4 of them on search
        await page.route('**/api/event/values?key=browser_name**', (route) => {
            const url = new URL(route.request().url())
            const searchValue = url.searchParams.get('value')

            if (!searchValue) {
                // Initial load - return 6 suggested values
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([
                        { name: 'Chrome' },
                        { name: 'Firefox' },
                        { name: 'Safari' },
                        { name: 'Edge' },
                        { name: 'Opera' },
                        { name: 'Brave' },
                    ]),
                })
            } else if (searchValue === 'e') {
                // Search for "e" - API only returns 4 values (missing Opera and Brave)
                // This simulates API limits or ranking differences
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([
                        { name: 'Chrome' },
                        { name: 'Firefox' },
                        { name: 'Edge' },
                        { name: 'Some Other Browser' }, // New value not in initial suggestions
                    ]),
                })
            } else {
                route.fulfill({
                    status: 200,
                    body: JSON.stringify([]),
                })
            }
        })

        // Navigate to insights and add property filter
        await page.goto(`/project/${workspace!.team_id}/insights/new`)
        await expect(page.getByTestId('insights-graph')).toBeVisible()

        await page.getByRole('button', { name: 'Add filter group' }).click()
        await page.getByRole('button', { name: 'Filter', exact: true }).click()

        const searchField = page.getByTestId('taxonomic-filter-searchfield')
        await searchField.waitFor({ state: 'visible' })
        await searchField.fill('browser_name')
        await page.locator('.taxonomic-list-row').first().click()

        // Click on property value input and wait for initial load
        const propertyValueInput = page.getByTestId('prop-val')
        await propertyValueInput.click()
        await page.waitForResponse('**/api/event/values?key=browser_name**')

        // Type "e" to trigger search
        await propertyValueInput.fill('e')
        await page.waitForResponse((response) => {
            const url = new URL(response.url())
            return url.pathname.includes('/api/event/values') && url.searchParams.get('value') === 'e'
        })
        await page.waitForTimeout(500)

        // Verify ALL 6 originally suggested values are still visible (even though API only returned 4)
        // Client-side filtering should show: Chrome, Firefox, Edge, Opera, Brave (all match "e")
        // Safari doesn't match "e" so it should be filtered out by Fuse.js
        await expect(page.getByText('Chrome')).toBeVisible()
        await expect(page.getByText('Firefox')).toBeVisible()
        await expect(page.getByText('Edge')).toBeVisible()
        await expect(page.getByText('Opera')).toBeVisible()
        await expect(page.getByText('Brave')).toBeVisible()

        // Verify the new value from API also appears
        await expect(page.getByText('Some Other Browser')).toBeVisible()

        // Verify suggested values (all 5 that match "e") have icons
        const options = page.locator('[data-attr^="prop-val-"]')
        const chromeOption = options.filter({ hasText: 'Chrome' }).first()
        const firefoxOption = options.filter({ hasText: 'Firefox' }).first()
        const edgeOption = options.filter({ hasText: 'Edge' }).first()
        const operaOption = options.filter({ hasText: 'Opera' }).first()
        const braveOption = options.filter({ hasText: 'Brave' }).first()
        const otherOption = options.filter({ hasText: 'Some Other Browser' }).first()

        await expect(chromeOption.locator('svg')).toBeVisible()
        await expect(firefoxOption.locator('svg')).toBeVisible()
        await expect(edgeOption.locator('svg')).toBeVisible()
        await expect(operaOption.locator('svg')).toBeVisible()
        await expect(braveOption.locator('svg')).toBeVisible()
        await expect(otherOption.locator('svg')).not.toBeVisible() // Not a suggested value
    })

    test('Suggested icon only appears during search', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
        await playwrightSetup.login(page, workspace)

        // Mock property values
        await page.route('**/api/event/values?key=browser_name**', (route) => {
            route.fulfill({
                status: 200,
                body: JSON.stringify([{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }]),
            })
        })

        // Navigate to insights and add property filter
        await page.goto(`/project/${workspace!.team_id}/insights/new`)
        await expect(page.getByTestId('insights-graph')).toBeVisible()

        await page.getByRole('button', { name: 'Add filter group' }).click()
        await page.getByRole('button', { name: 'Filter', exact: true }).click()

        const searchField = page.getByTestId('taxonomic-filter-searchfield')
        await searchField.waitFor({ state: 'visible' })
        await searchField.fill('browser_name')
        await page.locator('.taxonomic-list-row').first().click()

        // Click on property value input to show initial values
        const propertyValueInput = page.getByTestId('prop-val')
        await propertyValueInput.click()
        await page.waitForResponse('**/api/event/values?key=browser_name**')

        // Verify suggested icon does NOT appear when no search is active
        await expect(page.getByText('Chrome')).toBeVisible()
        const chromeOption = page.locator('[data-attr^="prop-val-"]').first()
        await expect(chromeOption.locator('svg')).not.toBeVisible()
    })
})
