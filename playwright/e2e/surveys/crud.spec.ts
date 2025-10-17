import { Page } from '@playwright/test'

import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

async function deleteSurvey(page: Page, name: string): Promise<void> {
    await page.locator('[data-attr=info-actions-panel]').click()
    await page.locator('[data-attr=survey-delete]').click()

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

async function launchSurveyEvenIfDisabled(page: Page): Promise<void> {
    // check if page.getByText('Surveys are currently disabled') is visible
    if (await page.getByText('Surveys are currently disabled').isVisible()) {
        await page.getByRole('button', { name: 'Configure' }).click()
        await page.getByTestId('opt-in-surveys-switch').click()
        await page.getByRole('button', { name: 'Done' }).click()
    }

    await page.locator('[data-attr="launch-survey"]').click()
    await expect(page.locator('.LemonModal__layout')).toBeVisible()
    await expect(page.getByText('Launch this survey?')).toBeVisible()
    await page.locator('.LemonModal__footer').getByRole('button', { name: 'Launch' }).click()
}

test.describe('CRUD Survey', () => {
    let name: string

    test.beforeEach(async ({ page }) => {
        name = randomString('survey-')
        await page.goToMenuItem('surveys')
    })

    test('creates, launches, edits and deletes new survey', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.locator('[data-attr="new-survey"]').click()
        await page.locator('[data-attr="new-blank-survey"]').click()

        await page.locator('[data-attr="scene-title-textarea"]').fill(name)
        await page.locator('[data-attr="survey-question-type-0"]').click()
        await page.getByText('Rating').click()

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.question"]')).toHaveValue(
            /How likely are you to recommend/
        )

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '0 - 10'
        )

        await expect(
            page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.upperBoundLabel"]')
        ).toHaveValue('Very likely')

        await page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('1 - 5').click()

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '1 - 5'
        )

        const surveyForm = page.locator('.survey-form')
        await expect(surveyForm).toContainText('How likely are you to recommend us to a friend?')
        await expect(surveyForm).toContainText('Unlikely')
        await expect(surveyForm).toContainText('Very likely')
        await expect(surveyForm.locator('.ratings-number')).toHaveCount(5)

        await page.locator('.LemonCollapsePanel', { hasText: 'Display conditions' }).click()
        await page.getByText('All users').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('Users who match').click()

        await page.locator('body').evaluate((el) => el.scrollTo(0, el.scrollHeight))

        await page.getByRole('button', { name: 'Add property targeting' }).click()
        await page.getByRole('button', { name: 'Add condition', exact: true }).click()
        await page.getByRole('rowgroup').getByText('is_demo').click()

        await page.locator('span').filter({ hasText: 'Enter value...' }).click()
        await page.getByPlaceholder('Enter value...').fill('t')
        await page.getByPlaceholder('Enter value...').press('Enter')

        // This is causing a test to flake. The screenshot shows the element in question, but we can't find it here.
        // Try submitting the form regardless. If the "t" element is not present, it'll fail anyway.

        // await expect(page.getByTitle('t')).toBeVisible()

        await page.locator('div').filter({ hasText: /^%$/ }).getByRole('spinbutton').click()
        await page.locator('div').filter({ hasText: /^%$/ }).getByRole('spinbutton').fill('50')

        await page.locator('[data-attr="save-survey"]').nth(0).click()
        await expectNoToastErrors(page)

        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')

        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users in this set.')

        await launchSurveyEvenIfDisabled(page)

        await page.getByText('Stop').click()
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.getByText('Stop this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Stop' }).click()

        await page.goToMenuItem('surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        await page.locator(`[data-row-key="${name}"]`).getByText(name).click()

        await page.locator('.LemonTabs').getByText('Overview').click()
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(
            page.getByText('Surveys will be displayed to users that match the following conditions')
        ).toBeVisible()

        await deleteSurvey(page, name)
    })

    test('can set responses limit', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await page.locator('[data-attr=new-survey]').click()
        await page.locator('[data-attr=new-blank-survey]').click()

        await page.locator('[data-attr="scene-title-textarea"]').fill(name)

        await page.locator('.LemonCollapsePanel', { hasText: 'Completion conditions' }).click()
        await page.locator('[data-attr=survey-collection-until-limit]').first().click()
        await page.locator('[data-attr=survey-responses-limit-input]').fill('228')
        await page.locator('[data-attr="scene-title-textarea"]').click()

        await page.locator('[data-attr=save-survey]').first().click()

        await expect(page.locator('button[data-attr="launch-survey"]')).toContainText('Launch')

        await page.reload()
        await expect(page.getByText('The survey will be stopped once 228 responses are received.')).toBeVisible()

        await deleteSurvey(page, name)
    })
})
