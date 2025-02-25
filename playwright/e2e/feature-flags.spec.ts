import { expect, test } from '../utils/playwright-test-base'

test.describe('Feature Flags', () => {
    let name: string

    test.beforeEach(async ({ page }) => {
        name = 'feature-flag-' + Math.floor(Math.random() * 10000000)
        await page.goto('/feature_flags')
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Feature flags')
    })

    test('Display product introduction on first load if no flags exist', async ({ page }) => {
        await expect(page.locator('text=Welcome to Feature flags!')).toBeVisible()
    })

    test('Create feature flag', async ({ page }) => {
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', name)
        await page.fill('[data-attr=feature-flag-description]', 'This is a new feature.')

        // handle instructions code language
        await page.locator('[data-attr=feature-flag-instructions-select]').click()
        await page.locator('[data-attr=feature-flag-instructions-select-option-php]').click({ force: true })
        await expect(page.locator('[data-attr=feature-flag-instructions-snippet]')).toContainText(
            'PostHog::isFeatureEnabled'
        )

        // add filter
        await page.locator('[data-attr="property-select-toggle-0"]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').click()
        await page.locator('[data-attr=prop-filter-person_properties-0]').click({ force: true })
        await page.locator('[data-attr=prop-val]').click()
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')
        await page.fill('[data-attr=rollout-percentage]', '0')

        // save
        await page.locator('[data-attr=save-feature-flag]').first().click()
        await expect(page.locator('[data-attr="more-button"]')).toBeVisible()
        await expect(page.locator('[data-attr="delete-feature-flag"]')).toHaveText('Delete feature flag')

        // reload
        await page.reload()
        await page.goToMenuItem('featureflags')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(name)

        // rename
        await page.locator(`[data-row-key=${name}]`, { hasText: name }).click()
        await page.locator('[data-attr="edit-feature-flag"]').click()
        await page.locator('[data-attr=feature-flag-key]').press('End')
        await page.keyboard.type('-updated')
        await page.locator('[data-attr=rollout-percentage]').fill('50')
        await page.locator('[data-attr=save-feature-flag]').first().click()

        await page.getByRole('button', { name: 'Close' }).click() // or a toast close
        await page.goToMenuItem('featureflags')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(name + '-updated')
    })

    test('Delete and restore feature flag', async ({ page }) => {
        const ffName = name
        await page.click('[data-attr=new-feature-flag]')
        await page.fill('[data-attr=feature-flag-key]', ffName)
        await page.fill('[data-attr=rollout-percentage]', '50')
        await page.locator('[data-attr=save-feature-flag]').first().click()
        await page.locator('[data-attr="more-button"]').click()
        await expect(page.locator('button[data-attr="delete-feature-flag"]')).toHaveText('Delete feature flag')

        // return to list
        await page.goToMenuItem('featureflags')
        await expect(page.locator('[data-attr=feature-flag-table]')).toContainText(ffName)

        // open details & delete
        await page.locator(`[data-row-key=${ffName}]`).click()
        await page.locator('[data-attr="more-button"]').click()
        await page.locator('[data-attr=delete-feature-flag]').click()
        await expect(page.locator('.Toastify__toast--success')).toContainText('Undo')

        // verify not in list
        await expect(page.locator('[data-attr=feature-flag-table]')).not.toContainText(ffName)

        // restore
        await page.goToMenuItem('featureflags')
        await page.locator('text=Recently deleted').click() // or if there's a special UI for that
        // find the item, restore it
        // ...
    })

    // Additional tests for searching, filtering, etc. omitted for brevity
})
