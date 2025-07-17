import { expect, test } from '../utils/playwright-test-base'
import { DashboardPage } from '../page-models/dashboardPage'
import { InsightPage } from '../page-models/insightPage'
import { randomString } from '../utils'

test.describe('Dashboard Pydantic Validation Errors', () => {
    let dashboardName: string
    let validInsightName: string
    let invalidInsightName: string

    test.beforeEach(async () => {
        dashboardName = randomString('Dashboard with Pydantic Error')
        validInsightName = randomString('Valid Insight')
        invalidInsightName = randomString('Invalid Insight with Pydantic Error')
    })

    test('Dashboard loads with pydantic error displayed in insight card', async ({ page }) => {
        // Create dashboard
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew(dashboardName)

        // Create and add valid insight
        const validInsightPage = new InsightPage(page)
        await validInsightPage.createNew(validInsightName)
        await validInsightPage.addToDashboard(dashboardName)

        // Create invalid insight with extra pydantic field
        const invalidInsightPage = new InsightPage(page)
        await invalidInsightPage.goToNew()
        await invalidInsightPage.rename(invalidInsightName)

        // Switch to JSON mode to manually edit the query
        await page.getByTestId('insight-json-tab').click()

        // Create an invalid query with extra field that will cause pydantic error
        const invalidQuery = JSON.stringify(
            {
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        math: 'total',
                    },
                ],
                trendsFilter: {},
                invalidExtraField: 'this will cause pydantic error', // This extra field will trigger validation error
            },
            null,
            2
        )

        // Clear and update the query editor
        await page.getByTestId('query-editor').locator('textarea').fill(invalidQuery)
        await page.getByTestId('query-editor-save').click()

        // Save the invalid insight
        await invalidInsightPage.save()

        // Add the invalid insight to dashboard
        await invalidInsightPage.addToDashboard(dashboardName)

        // Navigate back to dashboard
        await page.goto(`/dashboard`)
        await page.getByPlaceholder('Search for dashboards').fill(dashboardName)
        await page.getByText(dashboardName).click()

        // Check that dashboard loads successfully
        await expect(page.getByRole('heading', { name: dashboardName })).toBeVisible()

        // Check that valid insight displays normally
        await expect(page.locator('[data-attr="insight-card"]').filter({ hasText: validInsightName })).toBeVisible()

        // Check that invalid insight displays pydantic validation error
        const invalidInsightCard = page.locator('[data-attr="insight-card"]').filter({ hasText: invalidInsightName })
        await expect(invalidInsightCard.getByTestId('insight-empty-state')).toBeVisible()
        await expect(invalidInsightCard.getByText('There is a problem with this query')).toBeVisible()
        await expect(invalidInsightCard.getByText('ValidationError')).toBeVisible()
    })

    test('Invalid insight loads directly with pydantic error displayed', async ({ page }) => {
        // Create invalid insight
        const invalidInsightPage = new InsightPage(page)
        await invalidInsightPage.goToNew()
        await invalidInsightPage.rename(invalidInsightName)

        // Switch to JSON mode
        await page.getByTestId('insight-json-tab').click()

        // Create invalid query
        const invalidQuery = JSON.stringify(
            {
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        math: 'total',
                    },
                ],
                trendsFilter: {},
                invalidExtraField: 'this will cause pydantic error',
            },
            null,
            2
        )

        await page.getByTestId('query-editor').locator('textarea').fill(invalidQuery)
        await page.getByTestId('query-editor-save').click()

        // Save the insight
        await invalidInsightPage.save()

        // Get current URL to extract insight ID
        const currentUrl = page.url()
        const insightId = currentUrl.split('/').pop()

        // Visit the insight directly
        await page.goto(`/insights/${insightId}`)

        // Check that the insight page loads with validation error
        await expect(page.getByTestId('insight-empty-state')).toBeVisible()
        await expect(page.getByText('There is a problem with this query')).toBeVisible()
        await expect(page.getByText('ValidationError')).toBeVisible()
    })

    test('Clicking invalid insight from dashboard navigates correctly and shows error', async ({ page }) => {
        // Create dashboard
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew(dashboardName)

        // Create valid insight
        const validInsightPage = new InsightPage(page)
        await validInsightPage.createNew(validInsightName)
        await validInsightPage.addToDashboard(dashboardName)

        // Create invalid insight
        const invalidInsightPage = new InsightPage(page)
        await invalidInsightPage.goToNew()
        await invalidInsightPage.rename(invalidInsightName)

        await page.getByTestId('insight-json-tab').click()

        const invalidQuery = JSON.stringify(
            {
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        math: 'total',
                    },
                ],
                trendsFilter: {},
                invalidExtraField: 'this will cause pydantic error',
            },
            null,
            2
        )

        await page.getByTestId('query-editor').locator('textarea').fill(invalidQuery)
        await page.getByTestId('query-editor-save').click()
        await invalidInsightPage.save()
        await invalidInsightPage.addToDashboard(dashboardName)

        // Navigate to dashboard
        await page.goto(`/dashboard`)
        await page.getByPlaceholder('Search for dashboards').fill(dashboardName)
        await page.getByText(dashboardName).click()

        // Click on the invalid insight card title
        const invalidInsightCard = page.locator('[data-attr="insight-card"]').filter({ hasText: invalidInsightName })
        await invalidInsightCard.locator('h4').click()

        // Should navigate to the insight page
        await expect(page).toHaveURL(/\/insights\//)
        await expect(page).not.toHaveURL(/\/dashboard/)

        // Should show the validation error on the insight page
        await expect(page.getByTestId('insight-empty-state')).toBeVisible()
        await expect(page.getByText('There is a problem with this query')).toBeVisible()
        await expect(page.getByText('ValidationError')).toBeVisible()
    })
})
