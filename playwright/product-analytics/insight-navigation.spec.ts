import { expect, test } from '@playwright/test'

import { InsightType } from '~/types'

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
