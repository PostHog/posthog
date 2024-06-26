import { expect, test } from '@playwright/test'
import { urls } from 'scenes/urls'

import { ToastObject } from '../shared/toastObject'
import { InsightPage } from './insightPage'

test('can create insight', async ({ page }) => {
    const insight = new InsightPage(page)
    const toast = new ToastObject(page)

    // name field displays 'Unnamed' before save
    await page.goto(urls.insightNew())
    await expect(insight.topBarName, 'has no name').toContainText('Unnamed')

    // name field displays 'Pageview count' after save
    await insight.save()
    await expect(insight.topBarName, 'sets name').toContainText('Pageview count')
    await expect(toast.container, 'displays toast').toContainText('Insight saved')
})

test('can edit insight filter', async ({ page }) => {
    const insight = new InsightPage(page)
    await insight.createNew()

    // add an autocapture series
    await insight.withEdit(async () => {
        await page.getByTestId('add-action-event-button').click()
        await page.getByTestId('trend-element-subject-1').click()
        await page.getByText('Autocapture').click()
    })

    // labels in details table match
    const labels = await page.getByTestId('insights-table-graph').locator('.insights-label').allInnerTexts()
    expect(labels).toEqual(['Pageview', 'Autocapture'])
})
