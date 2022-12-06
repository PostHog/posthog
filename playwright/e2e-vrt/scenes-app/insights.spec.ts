import { toId } from '../../helpers/storybook'

import { test, expect } from '../../fixtures/storybook'

test.describe('trends insight', () => {
    test('displays line viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays line breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Line Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays bar viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Bar'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays bar breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Bar Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays value viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Value'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays value breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Value Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays area viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Area'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays area breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Area Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays number viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Number'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays table viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Table'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays table breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Table Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays pie viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Pie'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays pie breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends Pie Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays world map viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Trends World Map'))
        await storyPage.screenshotMainAppContent()
    })
})

test.describe('funnel insight', () => {
    test('displays left to right viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Left to Right'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays left to right breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Left to Right Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays top to bottom viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Top to Bottom'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays top to bottom breakdown viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Top to Bottom Breakdown'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays historical trends viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Historical Trends'))
        await storyPage.screenshotMainAppContent()
    })

    test('displays time to convert viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Funnel Time to Convert'))
        await storyPage.screenshotMainAppContent()
    })
})

test.describe('retention insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Retention'))
        await storyPage.screenshotMainAppContent()
    })

    // test('displays breakdown viz correctly', async ({ storyPage }) => {
    //     await storyPage.goto(toId('Scenes-App/Insights', 'Retention Breakdown'))
    //     await storyPage.screenshotMainAppContent()
    // })
})

test.describe('lifecycle insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Lifecycle'))
        await storyPage.screenshotMainAppContent()
    })
})

test.describe('stickiness insight', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'Stickiness'))
        await storyPage.screenshotMainAppContent()
    })
})

test.describe('user paths insights', () => {
    test('displays viz correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights', 'User Paths'))
        await storyPage.screenshotMainAppContent()
    })
})

test.describe('error states', () => {
    test('display the empty state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Empty State'))
        await storyPage.screenshotMainAppContent()
    })

    test('display the error state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Error State'))
        await storyPage.screenshotMainAppContent()
    })

    test('display the timeout state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Timeout State'))
        await storyPage.screenshotMainAppContent()
    })

    test('display the funnel single step state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Insights/Error States', 'Funnel Single Step'))
        await storyPage.screenshotMainAppContent()
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
