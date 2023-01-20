import { test as base } from '@playwright/test'

import { StorybookStoryPage } from '../pages/storybook'

type StorybookFixtures = {
    storyPage: StorybookStoryPage
}

export const test = base.extend<StorybookFixtures>({
    storyPage: async ({ page }, use) => {
        const storyPage = new StorybookStoryPage(page)
        await use(storyPage)
    },
})

export { expect } from '@playwright/test'
