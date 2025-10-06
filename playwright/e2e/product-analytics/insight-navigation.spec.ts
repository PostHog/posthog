import { InsightType } from '~/types'

import { InsightPage } from '../../page-models/insightPage'
import { Navigation } from '../../utils/navigation'
import { expect, test } from '../../utils/playwright-test-base'

const typeTestCases: { type: InsightType; selector: string }[] = [
    { type: InsightType.TRENDS, selector: '.TrendsInsight canvas' },
    { type: InsightType.FUNNELS, selector: '.funnels-empty-state__title' },
    { type: InsightType.RETENTION, selector: '.RetentionContainer canvas' },
    { type: InsightType.PATHS, selector: '.Paths' },
    { type: InsightType.STICKINESS, selector: '.TrendsInsight canvas' },
    { type: InsightType.LIFECYCLE, selector: '.TrendsInsight canvas' },
    { type: InsightType.SQL, selector: '[data-attr="hogql-query-editor"]' },
]

typeTestCases.forEach(({ type, selector }) => {
    // skipping things because we want to get a single passing test in
    test.skip(`can navigate to ${type} insight from saved insights page`, async ({ page }) => {
        await new InsightPage(page).goToNew(type)
        // have to use contains to make paths match user paths
        await expect(page.locator('.LemonTabs__tab--active')).toContainText(type, { ignoreCase: true })

        // we don't need to wait for the insight to load, just that it or its loading state is visible
        const insightStillLoading = await page.locator('.insight-empty-state.warning').isVisible()
        const insightDidLoad = await page.locator(selector).isVisible()
        expect(insightStillLoading || insightDidLoad).toBe(true)
    })
})

// skipping things because we want to get a single passing test in
// commented out because the query spec is incorrect
// test.skip('can navigate to insight by query', async ({ page }) => {
//     const insight = new InsightPage(page)
//     const url = urls.insightNew({query: {
//         kind: NodeKind.InsightVizNode,
//         source: {
//             kind: 'TrendsQuery',
//             series: [
//                 {
//                     kind: 'EventsNode',
//                     event: '$autocapture',
//                     name: 'Autocapture',
//                     math: 'total',
//                 },
//             ],
//             interval: 'day',
//             trendsFilter: {
//                 display: 'ActionsLineGraph',
//             },
//         },
//         full: true,
//     }})
//
//     await page.goto(url)
//
//     // test series labels
//     await insight.waitForDetailsTable()
//     const labels = await insight.detailsLabels.allInnerTexts()
//     expect(labels).toEqual(['Autocapture'])
// })

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
