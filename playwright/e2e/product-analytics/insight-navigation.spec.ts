import { InsightType } from '~/types'

import { InsightPage } from '../../page-models/insightPage'
import { Navigation } from '../../utils/navigation'
import { expect, test } from '../../utils/playwright-test-base'

// `InsightType` values are uppercase enum keys (TRENDS, FUNNELS, …) but the
// InsightsNav tab labels are sentence-cased ("Trends", "User Paths", …). The
// `expectedTabText` lets each case opt out of the case-insensitive enum match
// (e.g. PATHS → "User Paths") without bringing back per-type chart selectors —
// the old `.TrendsInsight` / `.funnels-empty-state__title` ones are dead.
const typeTestCases: { type: InsightType; expectedTabText: string }[] = [
    { type: InsightType.TRENDS, expectedTabText: 'Trends' },
    { type: InsightType.FUNNELS, expectedTabText: 'Funnels' },
    { type: InsightType.RETENTION, expectedTabText: 'Retention' },
    { type: InsightType.PATHS, expectedTabText: 'User Paths' },
    { type: InsightType.STICKINESS, expectedTabText: 'Stickiness' },
    { type: InsightType.LIFECYCLE, expectedTabText: 'Lifecycle' },
]

typeTestCases.forEach(({ type, expectedTabText }) => {
    test(`can navigate to ${type} insight from saved insights page`, async ({ page }) => {
        await new InsightPage(page).goToNew(type)
        await expect(page.locator('.LemonTabs__tab--active')).toContainText(expectedTabText)

        // EmptyStates.tsx tags every empty-state variant with this data-attr,
        // and the insight viz always swaps between empty state and a `<canvas>`
        // once data resolves. Treating either as success keeps the smoke test
        // stable across query backends and chart types.
        const emptyState = page.locator('[data-attr="insight-empty-state"]')
        const chartCanvas = page.locator('main canvas')
        await expect(emptyState.or(chartCanvas).first()).toBeVisible()
    })
})

test('can open event explorer as an insight', async ({ page }) => {
    const navigation = new Navigation(page)
    await navigation.openHome()

    await navigation.openMenuItem('activity')
    await page.getByTestId('data-table-export-menu').click()
    await page.getByTestId('open-json-editor-button').click()

    await expect(page.getByTestId('insight-json-tab')).toHaveCount(1)
})

test('does not show the json tab usually', async ({ page }) => {
    const navigation = new Navigation(page)
    await navigation.openHome()

    await navigation.openMenuItem('product-analytics')

    await expect(page.getByTestId('insight-json-tab')).toHaveCount(0)
})
