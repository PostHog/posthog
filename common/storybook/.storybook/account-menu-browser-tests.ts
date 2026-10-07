import { devices, expect, type Page } from '@playwright/test'

async function testProjectCreation(page: Page, storyId: string, dialogText: string): Promise<void> {
    const browser = page.context().browser()
    if (!browser) {
        throw new Error('Mobile project acceptance requires a browser')
    }
    expect(browser.browserType().name()).toBe('webkit')
    const context = await browser.newContext({ ...devices['iPhone 12'] })
    try {
        const mobilePage = await context.newPage()
        const url = new URL('/iframe.html', page.url())
        url.searchParams.set('id', storyId)
        url.searchParams.set('viewMode', 'story')
        await mobilePage.goto(url.toString())
        await expect(mobilePage.locator('[data-attr="project-creation-fixture-ready"]')).toBeAttached({
            timeout: 30000,
        })
        const account = mobilePage.locator('[data-attr="new-account-menu-button"]')
        if (!(await account.isVisible())) {
            await mobilePage.getByRole('button', { name: 'Open navigation', exact: true }).click()
        }
        await account.click()
        const create = mobilePage.locator('[data-attr="new-account-menu-create-project-icon-button"]')
        await expect(create).toBeVisible()
        await create.click()
        await expect(create).not.toBeVisible()
        await expect(mobilePage.getByRole('dialog').filter({ hasText: dialogText })).toBeVisible()
    } finally {
        await context.close()
    }
}

export const accountMenuBrowserTests: Record<string, (page: Page) => Promise<void>> = {
    'layout-mobile-project-creation--at-limit': (page) =>
        testProjectCreation(page, 'layout-mobile-project-creation--at-limit', 'projects'),
    'layout-mobile-project-creation--below-limit': (page) =>
        testProjectCreation(page, 'layout-mobile-project-creation--below-limit', 'Create project'),
}
