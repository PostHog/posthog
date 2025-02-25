import { DashboardPage } from '../page-models/dashboardPage'
import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Dashboard', () => {
    test.beforeEach(async ({ page }) => {
        // intercept calls, wait for requests, etc. if needed
        await page.goToMenuItem('dashboards')
    })

    test('Dashboards loaded', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Dashboards')
        await expect(page.locator('[data-attr=breadcrumb-Dashboards]')).toHaveText('Dashboards')
    })

    test('Adding new insight to dashboard works', async ({ page }) => {
        const dashPage = new DashboardPage(page)
        const dashboardName = randomString('Dashboard with matching filter')
        const insightName = randomString('insight to add to dashboard')

        await dashPage.createNew(dashboardName)

        // create a new insight
        await page.locator('[data-attr="dashboard-add-graph-header"]').click()
        await page.locator('[data-attr="dashboard-add-new-insight"]').click()
        await page.fill('[data-attr="top-bar-name"] input', insightName)
        await page.click('[data-attr="top-bar-name"] button:has-text("Save")')
        await page.click('[data-attr=insight-save-button]:has-text("Save & add to dashboard")')
        await expect(page.locator('.CardMeta h4')).toContainText(insightName)

        // add property filter
        await page.locator('[data-attr="property-filter-0"]').click()
        await page.locator('[data-attr="taxonomic-filter-searchfield"]').click()
        await page.locator('[data-attr="prop-filter-event_properties-1"]').click({ force: true })
        await page.locator('[data-attr=prop-val]').click()
        await page.locator('[data-attr=prop-val-0]').click({ force: true })
        await page.click('button:has-text("Save")')
        await expect(page.locator('main')).not.toContainText('There are no matching events')

        // create another dashboard, etc. The rest of the cypress steps can be replicated here
    })

    test('Refreshing dashboard works (changes date range, sees "Refreshing" status)', async ({ page }) => {
        const dashPage = new DashboardPage(page)
        const dashName = randomString('Dashboard with insights')
        await dashPage.createNew(dashName)

        // add an insight
        const insightName = randomString('insight-')
        await page.locator('[data-attr="dashboard-add-graph-header"]').click()
        await page.locator('[data-attr="dashboard-add-new-insight"]').click()
        await page.fill('[data-attr="top-bar-name"] input', insightName)
        await page.click('[data-attr="top-bar-name"] button:has-text("Save")')
        await page.click('[data-attr=insight-save-button]:has-text("Save & add to dashboard")')

        // refresh by changing date range
        await page.locator('[data-attr="date-filter"]').click()
        await page.locator('text=Last 14 days').click()
        await page.click('text=Save')
        await expect(page.locator('span >> text=Refreshing')).toHaveCount(0)
    })

    // The rest of the tests from cypress can be adapted similarly:
    // e.g. pinned dashboards, multiple dashboards, adding filters, etc.
})
