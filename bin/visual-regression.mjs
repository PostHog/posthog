import { launch } from 'puppeteer'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { PNG } from 'pngjs'
import pixelmatch from 'pixelmatch'

;(async () => {
    if (!existsSync('./visual-regression-screenshots/diffs')) {
        mkdirSync('./visual-regression-screenshots/diffs', { recursive: true })
    }

    const browser = await launch()
    // {headless:false}
    const page = await browser.newPage()

    try {
        console.log('checking lemon button types and statuses')
        await page.goto('https://storybook.posthog.net/?path=/docs/lemon-ui-lemon-button--default#types-and-statuses')
        await page.waitForSelector('#lemon-ui-lemon-button--types-and-statuses')
        // OMG storybook's delayed scroll is painful
        await page.evaluate(() => {
            console.log('PUPPETEER: evaluating!')
            var iframe = document.getElementById('storybook-preview-iframe')
            iframe.contentDocument.body.addEventListener('scroll', function () {
                console.log('PUPPETEER: reacting to scroll')
                window.clearTimeout(isScrolling)

                isScrolling = setTimeout(function () {
                    console.log('PUPPETEER: scrolling stopped!')
                    window.scrollingStartedAndStopped = true
                }, 100)
            })
        })

        await page.click('#lemon-ui-lemon-button--types-and-statuses')
        await page.waitForNetworkIdle()
        await page.waitForFunction('window.scrollingStartedAndStopped === true')
        await page.screenshot({ path: './visual-regression-screenshots/screenshot-button-types-and-statuses.png' })

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
                './visual-regression-screenshots/diffs/original-screenshot-button-types-and-statuses.png',
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
