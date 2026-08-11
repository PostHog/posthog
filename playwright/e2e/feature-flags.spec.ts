import { randomString } from '../utils'
import { expect, test } from '../utils/workspace-test-base'

// Flag evaluation (`/flags`) is served by the separate Rust flags service, which the
// e2e environment does not wire up: the dev proxy resolves `feature-flags` to
// host-gateway:3001 where nothing listens in CI, and the container reads the default
// `posthog` database rather than the e2e one. Until that service is plumbed into the
// e2e stack, this spec covers the browser-only creation path and stops at persistence.
test.describe('Feature flags', () => {
    test('a flag created in the UI is persisted and listed', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)
        const flagKey = randomString('e2e-flag')

        await test.step('create a 100% rollout flag via the UI', async () => {
            await page.goto('/feature_flags')
            await page.locator('[data-attr="new-feature-flag"]').click()
            await page.locator('[data-attr="blank-feature-flag-template"]').click()
            await page.locator('[data-attr="feature-flag-key"]').fill(flagKey)
            await page.locator('[data-attr="rollout-percentage"]').fill('100')
            const saveButton = page.locator('[data-attr="save-feature-flag"]').first()
            await expect(saveButton).toBeEnabled()
            await saveButton.click()
            await page.waitForURL(/\/feature_flags\/\d+/)
        })

        await test.step('the flag appears enabled in the flags list', async () => {
            await page.goto('/feature_flags')
            const row = page.locator('table tbody tr').filter({ hasText: flagKey })
            await expect(row).toBeVisible()
            await expect(row).toContainText('100%')
        })
    })
})
