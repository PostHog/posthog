import { toId } from '../../helpers/storybook'
import { test, expect } from '../../fixtures/storybook'

test.describe.skip('trends insight', () => {
    test('displays line viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays line breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays bar viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Bar'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays bar breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Bar Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays value viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Value'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays value breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Value Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays area viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Area'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays area breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Area Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays number viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Number'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays table viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Table'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays table breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Table Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays pie viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Pie'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays pie breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Pie Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays world map viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends World Map'))
        await storyPage.expectSceneScreenshot()
    })
})

test.describe('funnel insight', () => {
    test('displays left to right viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Left to Right'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays left to right breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Left to Right Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays top to bottom viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Top to Bottom'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays top to bottom breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Top to Bottom Breakdown'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays historical trends viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Historical Trends'))
        await storyPage.expectSceneScreenshot()
    })

    test('displays time to convert viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Time to Convert'))
        await storyPage.expectSceneScreenshot()
    })
})

test.describe('retention insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Retention'))
        await storyPage.expectSceneScreenshot()
    })

    // test('displays breakdown viz correctly', async ({ storyPage }) => {
    //     await storyPage.goto(toId('Scenes-App/Insights', 'Retention Breakdown'))
    //     await storyPage.screenshotMainAppContent()
    // })
})

test.describe('lifecycle insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Lifecycle'))
        await storyPage.expectSceneScreenshot()
    })
})

test.describe('stickiness insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Stickiness'))
        await storyPage.expectSceneScreenshot()
    })
})

// flaky test - needs investigation
// https://github.com/PostHog/posthog/pull/13185
test.skip('user paths insights', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'User Paths'))
        await storyPage.expectSceneScreenshot()
    })
})

test.describe('error states', () => {
    test('display the empty state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Empty State'))
        await storyPage.expectSceneScreenshot()
    })

    test('display the error state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Error State'))
        await storyPage.expectSceneScreenshot()
    })

    // test doesn't time out, was previously never timing out and just showing error state instead
    test.skip('display the timeout state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Timeout State'))
        await storyPage.expectSceneScreenshot()
    })

    test('display the funnel single step state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Funnel Single Step'))
        await storyPage.expectSceneScreenshot()
    })
})

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
