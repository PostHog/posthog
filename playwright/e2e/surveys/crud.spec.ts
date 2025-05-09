import { Page } from '@playwright/test'

import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

async function deleteSurvey(page: Page, name: string): Promise<void> {
    await page.locator('[data-attr=more-button]').click()
    await expect(page.locator('.Popover__content')).toBeVisible() // Wait for popover
    await page.locator('[data-attr=delete-survey]').click()

    // Handle the confirmation dialog
    await expect(page.locator('.LemonModal__layout')).toBeVisible()
    await expect(page.getByText('Delete this survey?')).toBeVisible()
    await page.getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByText('Active')).toBeVisible()
    await expect(page.locator(`[data-row-key="${name}"]`)).not.toBeVisible()
}

async function expectNoToastErrors(page: Page): Promise<void> {
    const toastErrors = await page.locator('[data-attr="toast-error"]').all()
    if (toastErrors.length > 0) {
        throw new Error(`Found ${toastErrors.length} toast errors`)
    }
}

test.describe('CRUD Survey', () => {
    let name: string

    test.beforeEach(async ({ page }) => {
        name = randomString('survey-') // Fix: Pass prefix to randomString
        await page.goToMenuItem('surveys') // Assuming a helper function for navigation
    })

    test('creates, launches and deletes new survey', async ({ page }) => {
        // load an empty page
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        // click via top right button
        await page.locator('[data-attr="new-survey"]').click()
        await page.locator('[data-attr="new-blank-survey"]').click()

        // select "add filter" and "property"
        await page.locator('[data-attr="survey-name"]').fill(name)
        await page.locator('[data-attr="survey-question-type-0"]').click()
        await page.getByText('Rating').click() // Assuming Popover content is visible

        // should pre-fill the question based on template
        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.question"]')).toHaveValue(
            /How likely are you to recommend/
        )

        // Check initial scale
        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '0 - 10'
        )

        await expect(
            page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.upperBoundLabel"]')
        ).toHaveValue('Very likely')

        // change the scale
        await page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]').click()
        // Wait for popover to be visible before clicking
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('1 - 5').click()

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '1 - 5'
        )

        // make sure the preview is updated
        const surveyForm = page.locator('.survey-form') // Reusable locator
        await expect(surveyForm).toContainText('How likely are you to recommend us to a friend?')
        await expect(surveyForm).toContainText('Unlikely')
        await expect(surveyForm).toContainText('Very likely')
        await expect(surveyForm.locator('.ratings-number')).toHaveCount(5)

        // add targeting filters
        await page.locator('.LemonCollapsePanel', { hasText: 'Display conditions' }).click()
        await page.getByText('All users').click()
        await expect(page.locator('.Popover__content')).toBeVisible() // Wait for popover
        await page.locator('.Popover__content').getByText('Users who match').click()

        // scroll down to bottom of page
        await page.locator('body').evaluate((el) => el.scrollTo(0, el.scrollHeight))

        await page.getByRole('button', { name: 'Add property targeting' }).click()
        await page.getByRole('button', { name: 'Add condition', exact: true }).click()
        await page.getByRole('rowgroup').getByText('is_demo').click()

        await page.locator('span').filter({ hasText: 'Enter value...' }).click()
        await page.getByPlaceholder('Enter value...').fill('t')
        await page.getByPlaceholder('Enter value...').press('Enter')

        await page.locator('div').filter({ hasText: /^%$/ }).getByRole('spinbutton').click()
        await page.locator('div').filter({ hasText: /^%$/ }).getByRole('spinbutton').fill('50')

        await page.locator('[data-attr="save-survey"]').nth(0).click()
        await expectNoToastErrors(page)

        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')

        // check preview release conditions
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        // // The Cypress test had this commented out, replicating here
        // await expect(page.locator('.FeatureConditionCard')).toContainText('is_demo equals true')
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users in this set.')

        // launch survey
        await page.locator('[data-attr="launch-survey"]').click()
        // Handle the confirmation dialog
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.getByText('Launch this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Launch' }).click()

        await page.getByText('Stop').click()
        // Handle the confirmation dialog
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.getByText('Stop this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Stop' }).click()

        // back to surveys
        await page.goToMenuItem('surveys') // Assuming helper
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        // back into survey
        await page.locator(`[data-row-key="${name}"]`).getByText(name).click()

        // edit
        await page.locator('[data-attr="more-button"]').click()
        await expect(page.locator('.Popover__content')).toBeVisible() // Wait for popover
        await page.locator('.Popover__content').getByText('Edit').click()

        // remove user targeting properties
        await page.locator('.LemonCollapsePanel', { hasText: 'Display conditions' }).click()
        await page.getByText('Remove all property targeting').click()

        // save
        await page.locator('[data-attr="save-survey"]').nth(0).click()

        // check preview release conditions
        await page.locator('.LemonTabs').getByText('Overview').click()
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).not.toBeVisible()

        // delete survey
        await deleteSurvey(page, name)
    })

    test('can set responses limit', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await page.locator('[data-attr=new-survey]').click()
        await page.locator('[data-attr=new-blank-survey]').click()

        await page.locator('[data-attr=survey-name]').fill(name)

        // Set responses limit
        await page.locator('.LemonCollapsePanel', { hasText: 'Completion conditions' }).click()
        await page.locator('[data-attr=survey-collection-until-limit]').first().click()
        await page.locator('[data-attr=survey-responses-limit-input]').fill('228')
        // Click away to potentially trigger save/update logic if needed
        await page.locator('[data-attr=survey-name]').click()

        // Save the survey
        await page.locator('[data-attr=save-survey]').first().click()
        await expect(page.locator('button[data-attr="launch-survey"]')).toContainText('Launch')

        await page.reload()
        // The Cypress test checked for "100228", assuming that was a typo and it should be 228
        await expect(page.getByText('The survey will be stopped once 228 responses are received.')).toBeVisible()
    })
})
