import { launch } from 'puppeteer'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { PNG } from 'pngjs'
import pixelmatch from 'pixelmatch'
;(async () => {
    if (!existsSync('./visual-regression-screenshots/diffs')) {
        mkdirSync('./visual-regression-screenshots/diffs', { recursive: true })
    }

    const browser = await launch({ headless: false })

    const page = await browser.newPage()

    try {
        console.log('checking lemon button types and statuses')
        await page.goto('https://storybook.posthog.net/?path=/docs/lemon-ui-lemon-button--default')
        await page.waitForSelector('#lemon-ui-lemon-button--types-and-statuses')

        await page.waitForNetworkIdle()
        await page.evaluate(() => {
            // avoids storybook's weird slow scolling
            const element = document
                .getElementById('storybook-preview-iframe')
                .contentDocument.getElementById('story--lemon-ui-lemon-button--types-and-statuses')
            element.scrollIntoViewIfNeeded(false)
        })

        await page.screenshot({
            path: './visual-regression-screenshots/screenshot-button-types-and-statuses.png',
            fullPage: true,
        })

        const screenshot = PNG.sync.read(
            readFileSync('./visual-regression-screenshots/screenshot-button-types-and-statuses.png')
        )
        const baseline = PNG.sync.read(
            readFileSync('./visual-regression-screenshots/baseline/screenshot-button-types-and-statuses.png')
        )
        const { width, height } = screenshot
        const diff = new PNG({ width, height })

        const numDiffPixels = pixelmatch(screenshot.data, baseline.data, diff.data, width, height, {
            threshold: 0.3,
            includeAA: true,
        })
        if (numDiffPixels) {
            console.log('detected ', numDiffPixels, ' pixels difference')
            writeFileSync(
                './visual-regression-screenshots/diffs/screenshot-button-types-and-statuses.png',
                PNG.sync.write(diff)
            )
            writeFileSync(
                './visual-regression-screenshots/baseline/screenshot-button-types-and-statuses.png',
                PNG.sync.write(screenshot)
            )
        } else {
            console.log('no diff detected for button types and statuses')
        }
    } catch (error) {
        console.error(error)
        await page.screenshot({ path: './visual-regression-screenshots/error.png' })
    } finally {
        await browser.close()
    }
})()
