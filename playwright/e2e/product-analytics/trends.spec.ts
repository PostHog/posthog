import { expect, test } from '../../utils/playwright-test-base'

test.describe('Trends', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
    })

    test('Add a pageview action filter', async ({ page }) => {
        await page.click('text=Add graph series')
        await page.click('[data-attr=trend-element-subject-1]')
        await page.locator('[data-attr=taxonomic-tab-actions]').click()
        await page.fill('[data-attr=taxonomic-filter-searchfield]', 'home')
        await page.click('text=Hogflix homepage view')
        await expect(page.locator('[data-attr=trend-element-subject-1]')).toContainText('Hogflix homepage view')
    })

    test('DAU on 1 element', async ({ page }) => {
        await page.click('[data-attr=math-selector-0]')
        await page.click('[data-attr=math-dau-0]')
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
    })

    test('Show property select dynamically', async ({ page }) => {
        await expect(page.locator('[data-attr=math-property-selector-0]')).toHaveCount(0)
        await page.click('[data-attr=math-selector-0]')
        await page.hover('[data-attr=math-node-property-value-0]')
        await page.click('[data-attr=math-node-property-value-0]')
        await expect(page.locator('[data-attr=math-property-select]')).toBeVisible()
    })

    test('Select HogQL expressions', async ({ page }) => {
        await expect(page.locator('[data-attr=math-property-selector-0]')).toHaveCount(0)
        await page.click('[data-attr=math-selector-0]')
        await page.hover('[data-attr=math-node-hogql-expression-0]')
        await page.click('[data-attr=math-node-hogql-expression-0]')
        await page.click('[data-attr=math-hogql-select-0]')
        await page.click('.CodeEditorResizeable')
        await page.keyboard.type('avg(1042) * 2048')
        await page.click('text=Update SQL expression')

        await page.click('[data-attr=chart-filter]')
        await page.click('text=Table')
        await expect(page.locator('text=2134016')).toBeVisible()
    })

    test('Apply property breakdown', async ({ page }) => {
        await page.click('text=Add breakdown')
        await page.click('text=Browser')
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
    })

    test('Show warning on MAU math in total value insight', async ({ page }) => {
        await page.click('[data-attr=chart-filter]')
        await page.click('text=Pie')
        await expect(page.locator('[data-attr=trend-pie-graph]')).toBeVisible()

        await page.click('[data-attr=math-selector-0]')
        await expect(page.locator('[data-attr=math-monthly_active-0] .LemonIcon')).toBeVisible()
        // or hover to see tooltip
    })

    test('Does not show delete button on single series', async ({ page }) => {
        await expect(page.locator('[data-attr=delete-prop-filter-0]')).toHaveCount(0)
    })
})
