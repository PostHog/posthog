import { Page } from '@playwright/test'

import { urls } from 'scenes/urls'

import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

const saveFeatureFlag = async (page: Page): Promise<string> => {
    const saveButton = page.locator('[data-attr="save-feature-flag"]').first()
    await expect(saveButton).toBeEnabled()
    const responsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/feature_flags') && resp.request().method() === 'POST'
    )
    await saveButton.click()
    await responsePromise
    // Saving redirects to the flag's own detail page (featureFlagLogic.saveFeatureFlagSuccess).
    // Stay here and return its URL — survey creation is available straight from the flag page,
    // which avoids the flaky round-trip of finding the just-created flag in the list search.
    await page.waitForURL(/\/feature_flags\/\d+/)
    return page.url()
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
    // Default multivariate now includes control/test at 50/50, so just rename them
    await page.locator('[data-attr="feature-flag-variant-key"][data-key-index="0"]').fill('test-1')
    await page.locator('[data-attr="feature-flag-variant-key"][data-key-index="1"]').fill('test-2')
}

const clickCreateSurvey = async (page: Page): Promise<void> => {
    // Open survey creation from the flag's own detail page (its scene panel), not the
    // feature-flag list search — that search intermittently never surfaces the just-created
    // flag, even on an isolated workspace. The panel may already be open (it persists across
    // navigation), so only toggle it open when the action isn't already visible.
    const createSurvey = page.locator('[data-attr="feature_flag-create-survey"]')
    if (!(await createSurvey.isVisible().catch(() => false))) {
        await page.locator('[data-attr="open-context-panel-button"]').first().click()
    }
    await createSurvey.click()
}

const goToSurveyOverview = async (page: Page): Promise<void> => {
    // Reaching "Create survey" opens the flag's context side panel, which persists across
    // navigation and overlays the survey tabs — intercepting the Overview click. Close it first.
    const closePanel = page.locator('[data-attr="context-panel-close-button"]')
    if (await closePanel.isVisible().catch(() => false)) {
        await closePanel.click()
    }
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
    await expect(page.locator('[data-attr="scene-name"]').first()).toContainText(name)
    await expect(page.locator('[data-attr="stop-survey"]')).toBeVisible()
}

// Run serially to keep per-test workspace setup off the critical path and avoid hammering
// the setup endpoint with concurrent organization_with_team calls.
test.describe.configure({ mode: 'serial' })

test.describe('Quick create survey from feature flag', () => {
    let name: string
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeEach(async ({ page, playwrightSetup }) => {
        // Dedicated empty workspace per test — no shared demo team, so the feature-flag
        // list only contains the flag this test creates (see playwright-test-base deprecation).
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)

        name = randomString('ff')
        await page.goto(urls.featureFlags())
        await expect(page.locator('h1')).toContainText('Feature flags')

        await page.evaluate(() => {
            window.posthog?.featureFlags?.override({})
        })

        // start ff creation
        await page.locator('[data-attr="new-feature-flag"]').click()
        await page.locator('[data-attr="feature-flag-key"]').fill(name)
        await page.locator('[data-attr="rollout-percentage"]').fill('100')
    })

    test('launch basic survey from single variant feature flag', async ({ page }) => {
        // use defaults for basic ff
        await saveFeatureFlag(page)

        await clickCreateSurvey(page)

        await launchSurvey(page, name)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch basic survey from multivariant feature flag', async ({ page }) => {
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page)

        await launchSurvey(page, name)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch variant-specific survey from multivariant feature flag', async ({ page }) => {
        // add variants
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page)

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
        await clickCreateSurvey(page)

        // add event — the picker is a TaxonomicFilter Events group with allowNonCapturedEvents,
        // so on an empty no_demo_data workspace nothing is listed until we search. Typing the
        // event name surfaces $autocapture (rendered with its "Autocapture" friendly label).
        await page.locator('.LemonButton').getByText('Add event').click()
        await page.locator('[data-attr="taxonomic-filter-searchfield"]').fill('$autocapture')
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
        await clickCreateSurvey(page)
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
        const flagUrl = await saveFeatureFlag(page)

        await clickCreateSurvey(page)
        await page.getByText(`Only users in the test-1 variant`).locator('..').locator('input').click()
        await launchSurvey(page, name)

        // Back to the flag's own page to spin up a second survey (test-2 variant).
        await page.goto(flagUrl)
        await clickCreateSurvey(page)
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
        await clickCreateSurvey(page)

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
        await expect(page.locator('[data-attr="scene-name"]').first()).toContainText(name)
        await expect(page.locator('[data-attr="launch-survey"]').getByText('Launch', { exact: true })).toBeVisible()
    })

    test('warning shown when surveys are disabled', async ({ page }) => {
        await saveFeatureFlag(page)

        // The team data comes from POSTHOG_APP_CONTEXT which is server-rendered into HTML.
        // API mocks don't work because teamLogic uses the preloaded context directly.
        // We need to intercept and modify the context before React hydrates.
        await page.addInitScript(() => {
            let _context: any = undefined
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    if (_context?.current_team) {
                        _context.current_team.surveys_opt_in = false
                    }
                    return _context
                },
                set(value) {
                    _context = value
                },
                configurable: true,
            })
        })

        await page.reload()
        await clickCreateSurvey(page)

        await expect(page.locator('label').getByText('Enable surveys')).toBeVisible()
    })
})
