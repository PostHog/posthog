import { expect, test } from '@playwright/test'

import { Navigation } from '../shared/navigation'
import { Toast } from '../shared/toast'
import { randomString } from '../utils'
import { DashboardPage } from './dashboardPage'
import { InsightPage } from './insightPage'

test.describe('changes to insight are reflected on dashboard', () => {
    test('adding the insight to a new dashboard (and removing it again)', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        // const dashboardPage = new DashboardPage(page)
        const toast = new Toast(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard()

        // verify that the insight is present on the dashboard
        // :FIXME: this is currently broken and needs a page reload
        // await dashboardPage.withReload(async () => {
        //     await expect(page.getByTestId('insight-card-title')).toHaveText(insightName)
        // })
        await page.reload({ waitUntil: 'networkidle' })
        await expect(page.getByTestId('insight-card-title')).toHaveText(insightName)

        // open the insight and remove it from the dashboard
        await page.getByText(insightName).click()
        await insightPage.removeDashboard()

        // verify the insight isn't present on the dashboard any more
        // :FIXME: this is currently broken and needs a page reload
        await expect(toast.container, 'displays toast').toContainText('Insight removed from dashboard')
        await page.goBack()
        await page.reload({ waitUntil: 'networkidle' })
        await expect(page.getByText('Dashboard empty')).toBeVisible()
        // await dashboardPage.withReload(
        //     async () => {
        //         await page.goBack()
        //         await expect(page.getByText('Dashboard empty')).toBeVisible()
        //     },
        //     async () => {
        //         await expect(toast.container, 'displays toast').toContainText('Insight removed from dashboard')
        //     }
        // )
    })

    test('renaming the insight', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        // const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // open the insight and edit the name
        await page.getByText(insightName).click()
        await insightPage.editName('new name')

        // go back to the dashboard an verify the name change
        await insightPage.openDashboard(dashboardName)
        // :FIXME: this is currently broken and needs a page reload
        // await dashboardPage.withReload(async () => {
        //     await expect(page.getByTestId('insight-card-title')).toHaveText('new name')
        // })
        await page.reload({ waitUntil: 'networkidle' })
        await expect(page.getByTestId('insight-card-title')).toHaveText('new name')
    })

    test('changing the insight filters', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        // const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // open the insight and add a second series
        await page.getByText(insightName).click()
        // :FIXME: This reload is necessary as the in-memory insight does not
        // yet have the dashboard. Saving without the reload would remove the
        // backend side connection as well.
        await page.reload({ waitUntil: 'networkidle' })
        await insightPage.withEdit(async () => {
            await insightPage.addEntityButton.click()
            await insightPage.secondEntity.click()
            await page.getByText('Autocapture').click()
        })

        // go back to the dashboard an verify the query change
        await insightPage.openDashboard(dashboardName)
        // :FIXME: this is currently broken and needs a page reload
        // await dashboardPage.withReload(async () => {
        //     await expect(page.getByTestId('insight-card-title')).toHaveText('new name')
        // })
        await page.reload({ waitUntil: 'networkidle' })
        await page.locator('.CardMeta').getByText('Show details').click()
        const entities = await page.locator('.PropertyKeyInfo').allInnerTexts()
        expect(entities).toEqual(['Pageview', 'Autocapture'])
    })

    test('deleting the insight', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const navigation = new Navigation(page)
        const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // open the insight and delete it
        await page.getByText(insightName).click()
        await insightPage.delete()

        // go back to the dashboard and verify the insight is gone
        await navigation.openMenuItem('dashboards')
        await page.getByPlaceholder('Search for dashboards').fill(dashboardName)
        await page.getByTestId('dashboard-name').first().click()
        await dashboardPage.withReload(async () => {
            await expect(page.getByText('Dashboard empty')).toBeVisible()
        })
    })
})

test.describe('changes on dashboard are reflected in insight', () => {
    test('renaming the insight', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // rename on dashboard
        await dashboardPage.renameFirstTile('new name')

        // open the insight
        await page.getByText(insightName).click()

        // verify the name change
        await insightPage.withReload(async () => {
            await expect(insightPage.topBarName).toHaveText('new name')
        })
    })

    test('removing the insight', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // remove from dashboard
        await dashboardPage.removeFirstTile()

        // open the insight
        await page.goBack()

        // verify the dashboard is not linked
        await insightPage.withReload(async () => {
            await insightPage.dashboardButton.click()
            await page.getByTestId('dashboard-searchfield').fill(dashboardName)
            await expect(page.getByTestId('dashboard-list-item').first().locator('.LemonButton')).toHaveText(
                'Add to dashboard'
            )
        })
    })

    test('duplicating the insight', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const dashboardPage = new DashboardPage(page)

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // remove from dashboard
        await dashboardPage.duplicateFirstTile()

        // open the duplicated insight
        await page.getByText(insightName + ' (copy)').click()

        // verify the dashboard is linked
        await insightPage.withReload(async () => {
            await insightPage.dashboardButton.click()
            await page.getByTestId('dashboard-searchfield').fill(dashboardName)
            await expect(page.getByTestId('dashboard-list-item').first().locator('.LemonButton')).toHaveText(
                'Remove from dashboard'
            )
        })
    })

    test('moving the insight to another dashboard', async ({ page }) => {
        const insightName = randomString('my-insight')
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew()

        // create an insight and add it to a new dashboard
        await insightPage.createNew(insightName)
        await insightPage.addToNewDashboard(dashboardName)

        // move to another dashboard
        await page.locator('.CardMeta').getByTestId('more-button').click()
        await page.locator('.Popover').getByText('Move to').click()
        await page.locator('.Popover[aria-level="1"] .LemonButton').first().click()

        // open the insight
        await page.goBack()

        // verify the insight was moved
        await insightPage.withReload(async () => {
            await insightPage.dashboardButton.click()
            await page.getByTestId('dashboard-searchfield').fill(dashboardName)
            await expect(page.getByTestId('dashboard-list-item').first().locator('.LemonButton')).toHaveText(
                'Add to dashboard'
            )
        })
    })

    test('renaming the dashboard', async ({ page }) => {
        const insightPage = new InsightPage(page)
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew()

        // create an insight and add it to a new dashboard
        await insightPage.createNew()
        await insightPage.addToNewDashboard()

        // rename the dashboard
        const newName = randomString('new-name')
        await dashboardPage.editName(newName)

        // open the insight
        await page.goBack()

        // verify the dashboard was renamed
        await insightPage.withReload(async () => {
            await insightPage.dashboardButton.click()
            await page.getByTestId('dashboard-searchfield').fill(newName)
            await expect(page.getByText(newName)).toBeVisible()
        })
    })

    // :FIXME: For an unknown reason the app behaves differently in the test
    // compare to doing the steps manually i.e. it displays a "Save" button
    // for the insight instead of the expected "Save and add to dashboard".
    test.skip('adding a new insight', async ({ page }) => {
        const insightPage = new InsightPage(page)
        const dashboardName = randomString('my-dashboard')
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew()

        await page.locator('.dashboard').getByTestId('dashboard-add-graph-header').click()
        await insightPage.saveButton.click()
        await page.goBack()

        // verify the dashboard is present in the insight
        await insightPage.withReload(async () => {
            await insightPage.dashboardButton.click()
            await page.getByTestId('dashboard-searchfield').fill(dashboardName)
            await expect(page.getByText(dashboardName)).toBeVisible()
        })
    })
})
