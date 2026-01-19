import { Page } from '@playwright/test'

import { urls } from 'scenes/urls'

import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

const saveFeatureFlag = async (page: Page): Promise<void> => {
    const saveButton = page.locator('[data-attr="save-feature-flag"]').first()
    await expect(saveButton).toBeEnabled()
    const responsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/feature_flags') && resp.request().method() === 'POST'
    )
    await saveButton.click()
    await responsePromise
    await page.goto(urls.featureFlags())
}

const expectFlagEnabled = async (page: Page, name: string): Promise<void> => {
    await expect(page.getByText(`Feature flag enabled for: ${name}`)).toBeVisible()
}

const expectVariant = async (page: Page, variant?: string): Promise<void> => {
    if (!variant) {
        return await expect(page.locator('.LemonTag').getByText('variant:')).not.toBeVisible()
    }

    await expect(page.locator('.LemonTag').getByText(`variant: ${variant}`)).toBeVisible()
}

const expectEvents = async (page: Page, events: string[]): Promise<void> => {
    if (events.length === 0) {
        return await expect(page.getByText('When the user sends the following events')).not.toBeVisible()
    }

    const eventsSpan = page.getByText('When the user sends the following events')
    const eventsSection = eventsSpan.locator('..')

    await expect(eventsSpan).toBeVisible()
    for (const event of events) {
        await expect(eventsSection.locator('.LemonTag').getByText(event)).toBeVisible()
    }
}

const addTwoVariants = async (page: Page): Promise<void> => {
    await page.getByText('Multiple variants with rollout percentages (A/B/n test)').click()
    await page.locator('[data-attr="feature-flag-variant-key"][data-key-index="0"]').fill('test-1')
    await page.getByText('Add variant').click()
    await page.locator('[data-attr="feature-flag-variant-key"][data-key-index="1"]').fill('test-2')
}

const clickCreateSurvey = async (page: Page, name: string): Promise<void> => {
    const row = page.locator(`[data-row-key="${name}"]`)
    await expect(row).toBeVisible()
    await row.locator('[data-attr="more-button"]').click()
    await page.locator('[data-attr="create-survey"]').click()
}

const goToSurveyOverview = async (page: Page): Promise<void> => {
    await page.locator('.LemonTabs__tab').getByText('Overview').click()
}

const launchSurvey = async (page: Page, name: string): Promise<void> => {
    const createButton = page.getByTestId('quick-survey-create')
    await expect(createButton).toBeEnabled()
    const responsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
    )
    await createButton.click()
    await responsePromise
    await page.waitForURL(/project\/(\d+)\/surveys\/([\w-]+)/)
    await expect(page.locator('.scene-tab-title').first()).toContainText(name)
    await expect(page.locator('[data-attr="stop-survey"]')).toBeVisible()
}

// CI is too slow, these all fail when run in parallel, will try to find a better solution soon
test.describe.configure({ mode: 'serial' })

test.describe('Quick create survey from feature flag', () => {
    let name: string

    test.beforeEach(async ({ page }) => {
        name = randomString('ff-')
        await page.goto(urls.featureFlags())
        await expect(page.locator('h1')).toContainText('Feature flags')

        await page.evaluate(() => {
            window.posthog?.featureFlags?.override({})
        })

        // start ff creation
        await page.getByText('New feature flag').click()
        await page.locator('[data-attr="feature-flag-key"]').fill(name)
        await page.locator('[data-attr="rollout-percentage"]').fill('100')
    })

    test('launch basic survey from single variant feature flag', async ({ page }) => {
        // use defaults for basic ff
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)

        await launchSurvey(page, name)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch basic survey from multivariant feature flag', async ({ page }) => {
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)
        const createButton = page.getByTestId('quick-survey-create')
        await expect(createButton).toBeEnabled()
        const responsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
        )
        await createButton.click()
        await responsePromise
        await page.waitForURL(/project\/(\d+)\/surveys\/([\w-]+)/)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch variant-specific survey from multivariant feature flag', async ({ page }) => {
        // add variants
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)

        // select variant test-1
        await page.getByText(`Only users in the test-1 variant`).locator('..').locator('input').click()

        await launchSurvey(page, name)
        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, 'test-1')
        await expectEvents(page, [])
    })

    test('launch survey with event', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)

        // add event
        await page.locator('.LemonButton').getByText('Add event').click()
        const autocaptureOption = page.locator('span[aria-label="Autocapture"]').getByText('Autocapture')
        await expect(autocaptureOption).toBeVisible()
        await autocaptureOption.click()

        await launchSurvey(page, name)
        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, ['$autocapture'])
    })

    test('survey responses visible in feature flag feedback tab', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)
        await launchSurvey(page, name)
        await goToSurveyOverview(page)

        const ffLink = page.getByText(`Feature flag enabled for: ${name}`).locator('a[href]')
        await expect(ffLink).toBeVisible()
        const ffUrl = await ffLink.getAttribute('href')
        await page.waitForLoadState('networkidle')
        await page.goto(ffUrl!)

        await page.locator('.LemonTabs__tab').getByText('User feedback').click()
        await expect(page.getByText('Filter survey results')).toBeVisible()
    })

    test('list of surveys in ff feedback tab when multiple surveys exist', async ({ page }) => {
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)
        await page.getByText(`Only users in the test-1 variant`).locator('..').locator('input').click()
        await launchSurvey(page, name)

        await page.goto(urls.featureFlags())
        await expect(page.locator('h1')).toContainText('Feature flags')
        await clickCreateSurvey(page, name)
        await page.getByText(`Only users in the test-2 variant`).locator('..').locator('input').click()
        await launchSurvey(page, name)

        await goToSurveyOverview(page)

        const ffLink = page.getByText(`Feature flag enabled for: ${name}`).locator('a[href]')
        await expect(ffLink).toBeVisible()
        const ffUrl = await ffLink.getAttribute('href')
        await page.waitForLoadState('networkidle')
        await page.goto(ffUrl!)

        await page.locator('.LemonTabs__tab').getByText('User feedback').click()
        await expect(page.locator('[data-attr="surveys-table"]')).toBeVisible()
    })

    test('create draft survey', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)

        await page
            .getByTestId('quick-survey-create')
            .locator('..')
            .locator('.LemonButtonWithSideAction__side-button button')
            .click()

        const saveAsDraftButton = page.getByText('Save as draft')
        await expect(saveAsDraftButton).toBeVisible()
        const responsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
        )
        await saveAsDraftButton.click()
        await responsePromise
        await page.waitForURL(/project\/(\d+)\/surveys\/([\w-]+)/)
        await expect(page.locator('.scene-tab-title').first()).toContainText(name)
        await expect(page.locator('[data-attr="launch-survey"]').getByText('Launch', { exact: true })).toBeVisible()
    })

    test('warning shown when surveys are disabled', async ({ page }) => {
        await saveFeatureFlag(page)

        await page.route('**/api/environments/@current/', async (route) => {
            const response = await route.fetch()
            const json = await response.json()
            json.surveys_opt_in = false

            await route.fulfill({ json })
        })

        await page.reload()
        await clickCreateSurvey(page, name)

        await expect(page.locator('label').getByText('Enable surveys')).toBeVisible()
    })
})
