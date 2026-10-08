import { expect, test } from '@playwright/test'

import { launchStagehand } from './bootstrap'

test('the CI Chromium build initializes the Stagehand runtime', async ({ playwright }) => {
    const session = await launchStagehand(playwright.chromium, { width: 1280, height: 720 }, 9222)
    try {
        expect(await session.page.evaluate(() => navigator.userAgent)).toContain('Chrome/')
        expect(await session.page.url()).toBe('about:blank')
    } finally {
        await session.close()
    }
})
