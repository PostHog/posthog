import { expect, test } from '@playwright/test'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { Navigation } from '../shared/navigation'
import { InsightPage } from './insightPage'

const typeTestCases: { type: InsightType; selector: string }[] = [
    { type: InsightType.TRENDS, selector: '.TrendsInsight canvas' },
    { type: InsightType.FUNNELS, selector: '.funnels-empty-state__title' },
    { type: InsightType.RETENTION, selector: '.RetentionContainer canvas' },
    { type: InsightType.PATHS, selector: '.Paths' },
    { type: InsightType.STICKINESS, selector: '.TrendsInsight canvas' },
    { type: InsightType.LIFECYCLE, selector: '.TrendsInsight canvas' },
    { type: InsightType.SQL, selector: '.DataTable' },
]

typeTestCases.forEach(({ type, selector }) => {
    test(`can navigate to ${type} insight from saved insights page`, async ({ page }) => {
        await new InsightPage(page).goToNew(type)
        await expect(page.locator(selector)).toHaveCount(1)
    })
})

test('can navigate to insight by filters', async ({ page }) => {
    const insight = new InsightPage(page)
    const url = urls.insightNew({
        insight: InsightType.TRENDS,
        interval: 'day',
        events: [{ id: '$autocapture', name: 'Autocapture', type: 'events' }],
    })

    await page.goto(url)

    // test series labels
    await insight.waitForDetailsTable()
    const labels = await insight.detailsLabels.allInnerTexts()
    expect(labels).toEqual(['Autocapture'])
})

test('can navigate to insight by query', async ({ page }) => {
    const insight = new InsightPage(page)
    const url = urls.insightNew(undefined, undefined, {
        kind: 'InsightVizNode',
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
