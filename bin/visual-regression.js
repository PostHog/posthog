const puppeteer = require('puppeteer')

;(async () => {
    const browser = await puppeteer.launch()
    const page = await browser.newPage()
    await page.goto('https://storybook.posthog.net/?path=/docs/lemon-ui-lemon-button--default#types-and-statuses')
    await page.screenshot({ path: 'screenshot-button-types-and-statuses.png' })

    await browser.close()
})()
