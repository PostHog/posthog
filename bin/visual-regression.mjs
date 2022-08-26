import { launch } from 'puppeteer'
import { readFileSync, writeFileSync } from 'fs'
import { PNG } from 'pngjs'
import pixelmatch from 'pixelmatch'
;(async () => {
    const browser = await launch()
    const page = await browser.newPage()
    try {
        await page.goto('https://storybook.posthog.net/?path=/docs/lemon-ui-lemon-button--default#types-and-statuses')
        await page.waitForSelector('#lemon-ui-lemon-button--types-and-statuses')
        await page.click('#lemon-ui-lemon-button--types-and-statuses')
        await page.screenshot({ path: './visual-regression-screenshots/screenshot-button-types-and-statuses.png' })

        const screenshot = PNG.sync.read(
            readFileSync('./visual-regression-screenshots/screenshot-button-types-and-statuses.png')
        )
        const baseline = PNG.sync.read(
            readFileSync('./visual-regression-screenshots/baseline/screenshot-button-types-and-statuses.png')
        )
        const { width, height } = screenshot
        const diff = new PNG({ width, height })

        const numDiffPixels = pixelmatch(screenshot.data, baseline.data, diff.data, width, height, { threshold: 0.1 })
        if (numDiffPixels) {
            console.log('detected ', numDiffPixels, ' pixels difference')
            writeFileSync(
                './visual-regression-screenshots/diffs/screenshot-button-types-and-statuses.png',
                PNG.sync.write(diff)
            )
        } else {
            ;('no diff detected for button types and statuses')
        }
    } catch (error) {
        console.error(error)
        await page.screenshot({ path: './visual-regression-screenshots/error.png' })
    } finally {
        await browser.close()
    }
})()
