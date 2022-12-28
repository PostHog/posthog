import { test, expect } from '../../fixtures/insights'

test.describe('insights', () => {
    test.beforeEach(async ({ authPage }) => {
        await authPage.login()
    })

    test('Saving an insight sets breadcrumbs', async ({ insightsPage, page }) => {
        await insightsPage.createInsight('test insight')

        await expect(page.getByTestId('breadcrumb-0')).toContainText('Hedgebox Inc.')
        await expect(page.getByTestId('breadcrumb-1')).toContainText('Hedgebox')
        await expect(page.getByTestId('breadcrumb-2')).toContainText('Insights')
        await expect(page.getByTestId('breadcrumb-3')).toContainText('test insight')
    })
})
