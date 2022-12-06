import { expect, Locator, Page } from '@playwright/test'

const STORYBOOK_URL: string = process.env.STORYBOOK_URL || 'http://localhost:6006'

export class StorybookStoryPage {
    readonly page: Page
    readonly mainAppContent: Locator
    readonly storyRoot: Locator

    constructor(page: Page) {
        this.page = page
        this.mainAppContent = page.locator('.main-app-content')
        this.storyRoot = page.locator('#root')
    }

    async goto(storyId: string): Promise<void> {
        const storyUrl = `${STORYBOOK_URL}/iframe.html?id=${storyId}&viewMode=story`
        await this.page.goto(storyUrl)
    }

    async screenshotMainAppContent(): Promise<void> {
        await expect(this.mainAppContent).toHaveScreenshot()
    }

    async screenshotStoryRoot(): Promise<void> {
        await expect(this.storyRoot).toHaveScreenshot()
    }
}
