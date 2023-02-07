import { toId } from '../../helpers/storybook'
import { test, expect } from '../../fixtures/storybook'

test.describe('tooltip', () => {
    test('displays correctly', async ({ page, storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line'))

        // hover over the graph to show the tooltip
        await page.locator('canvas').hover({
            position: {
                x: 412,
                y: 150,
            },
        })

        const tooltip = await page.locator('.InsightTooltip')
        await expect(tooltip).toHaveScreenshot()
    })
})

test.describe('annotations popover', () => {
    test('displays correctly', async ({ page, storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line'))

        // hover over the graph to show the annotations overlay
        await page.locator('.AnnotationsOverlay > button:nth-child(4)').hover()

        const popover = await page.locator('.AnnotationsPopover')
        await expect(popover).toHaveScreenshot()
    })
})
