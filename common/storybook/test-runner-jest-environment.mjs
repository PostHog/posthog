// Storybook 10's test-runner ships its own Playwright environment (which already
// calls setupPage) and no longer depends on jest-playwright-preset. Extend that
// environment and add only our failure-screenshot capture on top.
import BaseEnvironment from '@storybook/test-runner/playwright/custom-environment.js'

class CustomEnvironment extends BaseEnvironment {
    async handleTestEvent(event) {
        if (event.name === 'test_done' && event.test.errors.length > 0) {
            // Take screenshots on test failures - these become Actions artifacts
            const parentName = event.test.parent.parent.name.replace(/\W/g, '-').toLowerCase()
            const specName = event.test.parent.name.replace(/\W/g, '-').toLowerCase()
            await this.global.page
                .locator('body, main')
                .last()
                .screenshot({
                    path: `frontend/__snapshots__/__failures__/${parentName}--${specName}.png`,
                    timeout: 5000,
                })
                .catch(() => undefined)
        }
        await super.handleTestEvent(event)
    }
}

export default CustomEnvironment
