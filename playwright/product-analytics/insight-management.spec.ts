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
    const insightPage = await new InsightPage(page).createNew()

    // add an autocapture series
    await insightPage.withEdit(async () => {
        await insightPage.addEntityButton.click()
        await insightPage.secondEntity.click()
        await page.getByText('Autocapture').click()
    })

    // labels in details table match
    await insightPage.withReload(async () => {
        // wait for details table to be visible
        await insightPage.detailLabels.first().waitFor()

        // test series labels
        const labels = await insightPage.detailLabels.allInnerTexts()
        expect(labels).toEqual(['Pageview', 'Autocapture'])
    })
})

// test('can edit insight metadata', async ({ page }) => {
//     const insightPage = await new InsightPage(page).createNew()

//     // add an autocapture series
//     await insightPage.withEdit(async () => {
//         await insightPage.addEntityButton.click()
//         await insightPage.secondEntity.click()
//         await page.getByText('Autocapture').click()
//     })

//     // labels in details table match
//     await insightPage.withReload(async () => {
//         await expect(page.locator('.LemonTable--loading')).toHaveCount(0)

//         const labels = await insightPage.detailLabels.allInnerTexts()
//         expect(labels).toEqual(['Pageview', 'Autocapture'])
//     })
// })
