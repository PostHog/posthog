import { expect, test } from '../utils/playwright-test-base'

test.describe('Experiments', () => {
    let randomNum: number
    let experimentName: string
    let featureFlagKey: string

    test.beforeEach(async ({ page }) => {
        randomNum = Math.floor(Math.random() * 10000000)
        experimentName = `Experiment ${randomNum}`
        featureFlagKey = `experiment-${randomNum}`

        await page.goto('/experiments')
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Experiments')
    })

    test('create experiment', async ({ page }) => {
        await page.click('[data-attr=create-experiment]')
        await page.fill('[data-attr=experiment-name]', experimentName)
        await page.fill('[data-attr=experiment-feature-flag-key]', featureFlagKey)
        await page.fill('[data-attr=experiment-description]', 'This is the description of the experiment')

        // Edit variants
        await page.click('[data-attr="add-test-variant"]')
        await page.fill('input[data-attr="experiment-variant-key"][data-key-index="1"]', 'test-variant-1')
        await page.fill('input[data-attr="experiment-variant-key"][data-key-index="2"]', 'test-variant-2')

        // Save
        await page.click('[data-attr="save-experiment"]')
        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')
    })
})
