import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// can test that page matches a screenshot
test('login page', async ({ page }) => {
    await page.goto('http://127.0.0.1:8000')
    await page.locator('[data-attr="login-email"]').fill('user@posthog.com')
    await page.locator('[data-attr="password-login"]').click()
    await page.locator('[data-attr="password-login"]').click() //trigger validation errors
    await expect(page).toHaveScreenshot()
})

const violationFingerprints = (accessibilityScanResults: Record<string, any>): string => {
    const violationFingerprints = accessibilityScanResults.violations.map((violation: Record<string, any>) => ({
        rule: violation.id,
        // These are CSS selectors which uniquely identify each element with
        // a violation of the rule in question.
        targets: violation.nodes.map((node) => node.target),
    }))

    return JSON.stringify(violationFingerprints, null, 2)
}

// can test that page has allow-listed accessibility issues
test('should not have any automatically detectable accessibility issues', async ({ page }) => {
    await page.goto('http://127.0.0.1:8000')

    const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

    expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
})
