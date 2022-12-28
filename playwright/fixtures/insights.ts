import { test as base } from '@playwright/test'
import { InsightsPage } from '../pages/insights'
import { AuthPage } from '../pages/auth'

type InsightsFixtures = {
    insightsPage: InsightsPage
    authPage: AuthPage
}

export const test = base.extend<InsightsFixtures>({
    insightsPage: async ({ page }, use) => {
        // Set up the fixture.
        const insightsPage = new InsightsPage(page)
        await insightsPage.goto()
        // await insightsPage.addToDo('item1')
        // await insightsPage.addToDo('item2')

        // Use the fixture value in the test.
        await use(insightsPage)

        // Clean up the fixture.
        // await insightsPage.removeAll()
    },

    authPage: async ({ page }, use) => {
        await use(new AuthPage(page))
    },
})

export { expect } from '@playwright/test'
