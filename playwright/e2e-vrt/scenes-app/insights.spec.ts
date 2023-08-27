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
        // the tooltip animates towards the mouse cursor
        // if it hasn't finished moving then the screenshot will be wrong
        await page.waitForTimeout(250)

        // the hover is not exact and so the screenshot flaps
        // because it is one or two pixels off on the x-axis
        // so, we set the maxDiffPixelRatio to 0.01
        await expect(tooltip).toHaveScreenshot({ maxDiffPixelRatio: 0.01 })
    })
})

test.describe('annotations popover', () => {
    test('displays correctly', async ({ page, storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line'))

        // hover over the graph to show the annotations overlay
        await page.locator('.AnnotationsOverlay > button:nth-child(4)').hover()

        const popover = await page.locator('.AnnotationsPopover')
        // the tooltip animates towards the mouse cursor
        // if it hasn't finished moving then the screenshot will be wrong
        await page.waitForTimeout(250)

        // the hover is not exact and so the screenshot flaps
        // because it is one or two pixels off on the x-axis
        // so, we set the maxDiffPixelRatio to 0.01
        await expect(popover).toHaveScreenshot({ maxDiffPixelRatio: 0.01 })
    })
})
