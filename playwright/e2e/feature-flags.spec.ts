import { urls } from '../../frontend/src/scenes/urls'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Feature Flags', () => {
    let name: string

    test.beforeEach(async ({ page, featureFlags }) => {
        await featureFlags({})

        // Mock property definitions and values
        await page.route('**/api/projects/*/property_definitions?type=person*', async (route) => {
            await route.fulfill({
                status: 200,
                body: JSON.stringify([
                    {
                        name: 'is_demo',
                        count: 1,
                    },
                ]),
            })
        })

        await page.route('**/api/person/values?*', async (route) => {
            await route.fulfill({
                status: 200,
                body: JSON.stringify({
                    is_demo: ['true', 'false'],
                }),
            })
        })

        name = 'feature-flag-' + Math.floor(Math.random() * 10000000)
        await page.goto(urls.featureFlags())
    })

    test('Display product introduction when no feature flags exist', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
        await expect(page.getByText('Welcome to Feature flags!')).toBeVisible()
    })

    test('Create feature flag', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', name)
        await page.fill('[data-attr=feature-flag-description]', 'This is a new feature.')

        // Check feature flag instructions in different languages
        await page.click('[data-attr=feature-flag-instructions-select]')
        await page.click('[data-attr=feature-flag-instructions-select-option-php]', { force: true })
        await expect(page.locator('[data-attr=feature-flag-instructions-snippet]')).toContainText(
            /if \(PostHog::isFeatureEnabled\('.*', 'some distinct id'\)\) {/
        )
        await expect(page.locator('[data-attr=feature-flag-instructions-snippet]')).toContainText(
            / {4}\/\/ do something here/
        )
        await expect(page.locator('[data-attr=feature-flag-instructions-snippet]')).toContainText(/}/)
        await expect(page.locator('[data-attr=feature-flag-doc-link]')).toHaveAttribute(
            'href',
            'https://posthog.com/docs/libraries/php?utm_medium=in-product&utm_campaign=feature-flag#feature-flags'
        )

        // Add filter
        await page.click('[data-attr=property-select-toggle-0')
        await page.fill('[data-attr=taxonomic-filter-searchfield]', 'is_demo')
        await page.click('[data-attr=taxonomic-tab-person_properties]')
        await page.click('[data-attr=prop-filter-person_properties-0]', { force: true })
        await page.click('[data-attr=prop-val]')
        await page.click('[data-attr=prop-val-0]', { force: true })

        // Set rollout percentage
        await page.fill('[data-attr=rollout-percentage]', '0')

        // Save the feature flag
        await page.click('[data-attr=save-feature-flag]')

        // Verify delete button exists
        await page.click('[data-attr="more-button"]')
        await expect(page.locator('button[data-attr="delete-feature-flag"]')).toHaveText('Delete feature flag')

        // Verify data persists after reload
        await page.reload()

        // Go back to list and verify
        await page.click('[data-attr=menu-item-featureflags]')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(name)
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText('No users')

        // Edit flag
        await page.click(`[data-row-key=${name}]`)
        await page.click('[data-attr=edit-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', name + '-updated')
        await page.fill('[data-attr=rollout-percentage]', '50')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')
        await page.click('[data-attr=menu-item-featureflags]')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(name + '-updated')

        // Try out in Insights
        await page.click(`[data-row-key=${name}-updated] [data-attr=more-button]`)
        await page.getByText('Try out in Insights').click()
        await expect(page).toHaveURL(/.*\/insight/)
    })

    test('Delete and restore feature flag', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', name)
        await page.fill('[data-attr=rollout-percentage]', '50')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')

        // Verify delete button
        await page.click('[data-attr="more-button"]')
        await expect(page.locator('button[data-attr="delete-feature-flag"]')).toHaveText('Delete feature flag')

        await page.click('[data-attr=menu-item-featureflags]')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(name)
        await page.click(`[data-row-key=${name}]`)
        await page.click('[data-attr="more-button"]')
        await page.click('[data-attr=delete-feature-flag]')
        await expect(page.locator('.Toastify')).toContainText('Undo')

        // Verify flag is deleted
        await page.click('[data-attr=menu-item-featureflags]')
        await expect(page.locator('[data-attr=feature-flag-table]')).not.toContainText(name)

        // Navigate back and verify edit disabled
        await page.goBack()
        await expect(page.locator('button[data-attr="edit-feature-flag"]')).toHaveAttribute('aria-disabled', 'true')

        // Check usage tab
        await page.getByRole('tab', { name: 'Usage' }).click()
        await expect(page.locator('[data-attr=feature-flag-usage-container]')).not.toBeVisible()
        await expect(page.locator('[data-attr=feature-flag-usage-deleted-banner]')).toBeVisible()

        // Restore flag
        await page.click('[data-attr="more-button"]')
        await expect(page.locator('button[data-attr="restore-feature-flag"]')).toHaveText('Restore feature flag')
        await page.click('button[data-attr="restore-feature-flag"]')

        // Verify usage tab after restore
        await page.getByRole('tab', { name: 'Usage' }).click()
        await expect(page.locator('[data-attr=feature-flag-usage-container]')).toBeVisible()
        await expect(page.locator('[data-attr=feature-flag-usage-deleted-banner]')).not.toBeVisible()

        // Verify after refresh
        await page.reload()
        await expect(page.locator('button[data-attr="edit-feature-flag"]')).not.toHaveAttribute('aria-disabled', 'true')
    })

    test('Search feature flags', async ({ page }) => {
        // Create searchable flag
        const searchableFlagName = 'searchable-flag-' + Math.floor(Math.random() * 10000000)
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', searchableFlagName)
        await page.fill('[data-attr=rollout-percentage]', '0')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')
        await page.click('[data-attr=menu-item-featureflags]')

        // Create non-searchable flag
        const nonSearchableFlagName = 'never-shows-up-' + Math.floor(Math.random() * 10000000)
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', nonSearchableFlagName)
        await page.fill('[data-attr=rollout-percentage]', '0')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')
        await page.click('[data-attr=menu-item-featureflags]')

        // Search
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
        const searchTerm = searchableFlagName.substring(8, 20)
        await page.fill('[data-attr=feature-flag-search]', searchTerm)
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(searchableFlagName)
        await expect(page.locator('[data-attr=feature-flag-table]')).not.toContainText(nonSearchableFlagName)

        // Verify search persists
        await expect(page).toHaveURL(new RegExp(`search=${searchTerm}`))
        await page.reload()
        await expect(page.locator('[data-attr=feature-flag-search]')).toHaveValue(searchTerm)
    })

    test('Filter and sort feature flags', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')

        // Create disabled flag
        const disabledPrefixFlagName = `disabled-${name}`
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', disabledPrefixFlagName)
        await page.click('[data-attr=feature-flag-enabled-checkbox]')
        await page.fill('[data-attr=rollout-percentage]', '0')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')
        await page.click('[data-attr=menu-item-featureflags]')

        // Filter by status
        await page.click('[data-attr=feature-flag-select-status')
        await page.click('[data-attr=feature-flag-select-status-disabled]')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(disabledPrefixFlagName)
        await expect(page).toHaveURL(/.*active=false/)

        // Verify filters persist
        await page.reload()
        await expect(page.locator('[data-attr=feature-flag-select-status]')).toContainText('Disabled')

        // Sort by status
        await page.click('[data-attr=feature-flag-select-status')
        await page.click('[data-attr=feature-flag-select-status-all]')
        await page.locator('[data-attr=feature-flag-table]').getByText('Status').click()
        await expect(page.locator(`[data-row-key=${disabledPrefixFlagName}]`).locator('..').first()).toContainText(
            'Disabled'
        )
    })

    test('Show empty state when filters are too restrictive', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')

        const noResultsSearchTerm = 'zzzzzzzzzzz_no_flags_with_this_name_zzzzzzzzzzz'
        await page.fill('[data-attr=feature-flag-search]', noResultsSearchTerm)
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(
            'No results for this filter, change filter or create a new flag.'
        )
        await expect(page.locator('[data-attr=feature-flag-table]')).not.toContainText(noResultsSearchTerm)
    })

    test('Enable and disable feature flags from list', async ({ page }) => {
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')

        // Create enabled flag
        const togglablePrefixFlagName = `to-toggle-${name}`
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', togglablePrefixFlagName)
        await page.fill('[data-attr=rollout-percentage]', '0')
        await page.click('[data-attr=save-feature-flag]')
        await page.click('[data-attr=toast-close-button]')
        await page.click('[data-attr=menu-item-featureflags]')

        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
        await page.fill('[data-attr=feature-flag-search]', togglablePrefixFlagName)
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(togglablePrefixFlagName)
    })
})
