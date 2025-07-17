import { expect, test } from '../utils/playwright-test-base'
import { DashboardPage } from '../page-models/dashboardPage'
import { InsightPage } from '../page-models/insightPage'
import { randomString } from '../utils'

test.describe('Dashboard Pydantic Validation Errors', () => {
    let dashboardName: string
    let validInsightName: string
    let invalidInsightName: string

    test.beforeEach(async ({ page }) => {
        dashboardName = randomString('Dashboard with Pydantic Error')
        validInsightName = randomString('Valid Insight')
        invalidInsightName = randomString('Invalid Insight with Pydantic Error')

        // Create dashboard through UI
        const dashboardPage = new DashboardPage(page)
        await dashboardPage.createNew(dashboardName)

        // Create valid insight using simple approach (avoiding the problematic editName method)
        const validInsightPage = new InsightPage(page)
        await validInsightPage.goToNew()
        // Set name using keyboard approach that works (like Cypress)
        await page.getByTestId('top-bar-name').getByRole('button').click()
        await page.getByTestId('top-bar-name').getByRole('textbox').clear()
        await page.getByTestId('top-bar-name').getByRole('textbox').fill(validInsightName)
        await page.keyboard.press('Enter')
        await validInsightPage.save()
        await validInsightPage.addToDashboard(dashboardName)

        // Create another insight that we'll corrupt later
        const invalidInsightPage = new InsightPage(page)
        await invalidInsightPage.goToNew()
        // Set name using keyboard approach
        await page.getByTestId('top-bar-name').getByRole('button').click()
        await page.getByTestId('top-bar-name').getByRole('textbox').clear()
        await page.getByTestId('top-bar-name').getByRole('textbox').fill(invalidInsightName)
        await page.keyboard.press('Enter')
        await invalidInsightPage.save()
        await invalidInsightPage.addToDashboard(dashboardName)

        // Now corrupt the second insight's query field via Django admin interface
        // This simulates how bad data gets into production through migrations/deployments

        // Navigate to Django admin to edit the insight directly
        await page.goto('/admin/posthog/insight/')
        await page.waitForLoadState('networkidle')

        // Look for our insight in the table (it should be one of the most recent)
        const insightRow = page.locator('tr').filter({ hasText: invalidInsightName })
        await insightRow.locator('a').first().click()
        await page.waitForLoadState('networkidle')

        // Find and edit the query field (it's a JSONField in Django admin)
        const queryTextarea = page.locator('textarea[name="query"]')
        await queryTextarea.waitFor()

        // Get the current query JSON and add an invalid field
        const currentQuery = await queryTextarea.inputValue()
        const queryObj = JSON.parse(currentQuery)
        queryObj.invalidExtraField = 'this will cause pydantic error'

        // Update the query field with corrupted data
        await queryTextarea.fill(JSON.stringify(queryObj, null, 2))

        // Save the changes
        await page.getByRole('button', { name: 'Save' }).click()
        await page.waitForLoadState('networkidle')
    })

    test('Dashboard loads with pydantic error displayed in insight card', async ({ page }) => {
        // Navigate to the dashboard
        await page.goto('/dashboard')
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
        // Navigate to insights list and search for the invalid insight
        await page.goto('/insights')
        await page.getByPlaceholder('Search for insights').fill(invalidInsightName)

        // Click on the insight to navigate to it
        await page.getByText(invalidInsightName).click()

        // Check that the insight page loads with validation error
        await expect(page.getByTestId('insight-empty-state')).toBeVisible()
        await expect(page.getByText('There is a problem with this query')).toBeVisible()
        await expect(page.getByText('ValidationError')).toBeVisible()
    })

    test('Clicking invalid insight from dashboard navigates correctly and shows error', async ({ page }) => {
        // Navigate to the dashboard
        await page.goto('/dashboard')
        await page.getByPlaceholder('Search for dashboards').fill(dashboardName)
        await page.getByText(dashboardName).click()

        // Click on the invalid insight card title to navigate to insight page
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
