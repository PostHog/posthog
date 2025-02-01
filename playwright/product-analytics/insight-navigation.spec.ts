import { expect, test } from '@playwright/test'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { Navigation } from '../shared/navigation'
import { InsightPage } from './insightPage'
import { NodeKind } from '~/queries/schema'

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
    test(`can navigate to ${type} insight from saved insights page`, async ({ page }) => {
        const insightQuery = page.waitForRequest((req) => {
            return !!(req.url().match(/api\/environments\/\d+\/query/) && req.method() === 'POST')
        })
        await new InsightPage(page).goToNew(type)
        await insightQuery
        await expect(page.locator('.LemonTabs__tab--active')).toHaveText(type, {ignoreCase: true})

        // we don't need to wait for the insight to load, just that it or its loading state is visible
        const insightStillLoading = await page.locator('.insight-empty-state.warning').isVisible()
        const insightDidLoad = await page.locator(selector).isVisible()
        expect(insightStillLoading || insightDidLoad).toBe(true)
    })
})

test('can navigate to insight by query', async ({ page }) => {
    const insight = new InsightPage(page)
    const url = urls.insightNew(undefined, undefined, {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$autocapture',
                    name: 'Autocapture',
                    math: 'total',
                },
            ],
            interval: 'day',
            trendsFilter: {
                display: 'ActionsLineGraph',
            },
        },
        full: true,
    })

    await page.goto(url)

    // test series labels
    await insight.waitForDetailsTable()
    const labels = await insight.detailsLabels.allInnerTexts()
    expect(labels).toEqual(['Autocapture'])
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

    await navigation.openMenuItem('savedinsights')

    await expect(page.getByTestId('insight-json-tab')).toHaveCount(0)
})