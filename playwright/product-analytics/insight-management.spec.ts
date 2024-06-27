import { expect, test } from '@playwright/test'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { ToastObject } from '../shared/toastObject'
import { InsightPage } from './insightPage'

test('can create insight', async ({ page }) => {
    const insight = new InsightPage(page)
    const toast = new ToastObject(page)

    // name field displays 'Unnamed' before save
    await page.goto(urls.insightNew())
    await expect(insight.topBarName, 'has no name').toContainText('Unnamed')

    // save the insight
    await insight.save()

    // name field displays 'Pageview count' after save
    await insight.withReload(
        async () => {
            await expect(insight.topBarName, 'sets name').toContainText('Pageview count')
        },
        async () => {
            await expect(toast.container, 'displays toast').toContainText('Insight saved')
        }
    )
})

test('can edit insight query', async ({ page }) => {
    const insight = await new InsightPage(page).createNew()

    // add an autocapture series
    await insight.withEdit(async () => {
        await insight.addEntityButton.click()
        await insight.secondEntity.click()
        await page.getByText('Autocapture').click()
    })

    // labels in details table match
    await insight.withReload(async () => {
        await insight.waitForDetailsTable()

        // test series labels
        const labels = await insight.detailsLabels.allInnerTexts()
        expect(labels).toEqual(['Pageview', 'Autocapture'])
    })
})

test('can edit insight metadata', async ({ page }) => {
    const insight = await new InsightPage(page).createNew()
    const toast = new ToastObject(page)

    await insight.editName('new name')

    await insight.withReload(
        async () => {
            await expect(insight.topBarName).toContainText('new name')
        },
        async () => {
            await expect(toast.container, 'displays toast').toContainText('Updated insight')
        }
    )
})

test('can undo insight metadata edit', async ({ page }) => {
    const insight = await new InsightPage(page).createNew(InsightType.TRENDS, 'old name')
    const toast = new ToastObject(page)

    await insight.editName('new name')
    await toast.undo()

    await insight.withReload(
        async () => {
            await expect(insight.topBarName).toContainText('old name')
        },
        async () => {
            await expect(toast.container, 'displays toast').toContainText('Insight change reverted')
        }
    )
})
