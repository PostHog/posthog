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

    test('shows get started state on first load', async ({ page }) => {
        // load an empty page
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await expect(page.getByText('Create your first survey')).toBeVisible()

        // go to create a new survey
        await page.locator('[data-attr="create-survey"]').click()
        await page.locator('[data-attr="new-blank-survey"]').click()

        await page.locator('[data-attr="survey-name"]').fill(name)
        await expect(page.locator('[data-attr="survey-name"]')).toHaveValue(name)

        // save
        // get 1st element matching the selector (Playwright uses 0-based index)
        await page.locator('[data-attr="save-survey"]').nth(0).click()
        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')

        // back to surveys
        await page.goToMenuItem('surveys') // Assuming helper
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)
        await expect(page.getByText('Create your first survey')).not.toBeVisible()

        // back into survey
        await page.locator(`[data-row-key="${name}"]`).getByText(name).click()

        // delete survey
        await page.locator('[data-attr="more-button"]').click()
        // Wait for popover content to be visible before clicking delete
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('Delete').click()

        // Handle the confirmation dialog
        await expect(page.locator('.LemonModal__footer')).toBeVisible()
        await expect(page.getByText('Delete this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Delete' }).click()

        await page.goToMenuItem('surveys') // Assuming helper
        // Check that the table body doesn't exist, implying no surveys
        await expect(page.locator('tbody')).not.toBeVisible()
    })

    test('creates a new survey', async ({ page }) => {
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

        // refresh, see survey show up on page
        await page.reload()
        await expect(page.getByText('Loading results...')).toBeVisible()
        await expect(page.getByText('Loading results...')).not.toBeVisible()

        await expect(page.getByText('Total Impressions by Unique Users')).toBeVisible()

        // Update the stop survey part
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

    test('deletes a survey', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await page.locator('[data-attr=new-survey]').click()
        await page.locator('[data-attr=new-blank-survey]').click()
        await page.locator('[data-attr=survey-name]').fill(name)
        await expect(page.locator('[data-attr=survey-name]')).toHaveValue(name)
        await page.locator('[data-attr=save-survey]').first().click()
        // await page.locator('[data-attr="toast-close-button"]').click()

        // after save there should be a launch button
        await expect(page.locator('button[data-attr="launch-survey"]')).toContainText('Launch')

        await page.goToMenuItem('surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)
        await page.locator(`[data-row-key="${name}"]`).getByText(name).click()

        await deleteSurvey(page, name)
    })

    test('duplicates a survey', async ({ page }) => {
        // create survey
        await page.locator('[data-attr=new-survey]').click()
        await page.locator('[data-attr=new-blank-survey]').click()
        await page.locator('[data-attr=survey-name]').fill(name)
        await expect(page.locator('[data-attr=survey-name]')).toHaveValue(name)

        // Add user targetting criteria
        await page.locator('.LemonCollapsePanel', { hasText: 'Display conditions' }).click()
        await page.getByText('All users').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('Users who match').click()
        await page.getByText('Add property targeting').click()
        await page.locator('[data-attr="property-select-toggle-0"]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('[data-attr="prop-filter-person_properties-0"]').click()
        await page.locator('[data-attr=prop-val]').nth(1).focus()
        await page.locator('[data-attr=prop-val]').nth(1).fill('true')
        await page.locator('[data-attr=prop-val]').nth(1).press('Enter')
        await page.locator('[data-attr="rollout-percentage"]').click()
        await page.locator('[data-attr="rollout-percentage"]').clear()
        await page.locator('[data-attr="rollout-percentage"]').fill('50')

        await page.locator('[data-attr=save-survey]').first().click()

        // Launch the survey first, the duplicated one should be in draft
        await page.locator('[data-attr="launch-survey"]').click()
        // Handle the confirmation dialog
        await expect(page.locator('.LemonModal__footer')).toBeVisible()
        await expect(page.getByText('Launch this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Launch' }).click()

        // try to duplicate survey
        await page.locator('[data-attr=more-button]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('[data-attr=duplicate-survey]').click()

        // if the survey is duplicated, try to view it & verify a copy is created
        await expect(page.locator('[data-attr=success-toast]')).toContainText('duplicated')
        await page.locator('[data-attr=success-toast]').locator('button').click()
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText(`${name} (copy)`)

        // check if it launched in a draft state
        await expect(page.locator('button[data-attr="launch-survey"]')).toContainText('Launch')

        // check if targetting criteria is copied
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toContainText('is_demo equals true')
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users in this set.')

        // delete the duplicated survey
        const duplicatedName = `${name} (copy)`
        await page.locator('[data-attr=more-button]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('[data-attr=delete-survey]').click()
        await expect(page.locator('.LemonModal__footer')).toBeVisible()
        await expect(page.getByText('Delete this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Delete' }).click()

        // Archive the original survey
        await page.goToMenuItem('surveys')
        await page.locator('[data-attr=surveys-table]').locator(`[data-row-key="${name}"]`).locator('a').click()
        await page.locator('[data-attr=stop-survey]').click()
        await expect(page.locator('.LemonModal__footer')).toBeVisible()
        await expect(page.getByText('Stop this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Stop' }).click()
        await page.locator('[data-attr=more-button]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('[data-attr=archive-survey]').click()
        await expect(page.locator('.LemonModal__footer')).toBeVisible()
        await expect(page.getByText('Archive this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Archive' }).click()

        // check if the duplicated survey is created with draft state
        // (This seems to duplicate the *archived* survey again? Following Cypress logic)
        await page.locator('[data-attr=more-button]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('[data-attr=duplicate-survey]').click()
        await page.goToMenuItem('surveys')
        await expect(
            page
                .locator('[data-attr=surveys-table]')
                .locator(`[data-row-key="${duplicatedName}"]`)
                .locator('[data-attr=status]')
        ).toContainText('DRAFT')
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

    test('creates a new survey with branching logic', async ({ page }) => {
        // Mock the feature flag context like in the Cypress test
        await page.evaluate(() => {
            // Add checks to satisfy TypeScript
            if (window.POSTHOG_APP_CONTEXT?.current_user?.organization) {
                window.POSTHOG_APP_CONTEXT.current_user.organization.available_product_features = [
                    {
                        key: 'surveys_multiple_questions',
                        name: 'Multiple questions',
                        description: 'Ask up to 10 questions in a single survey.',
                        unit: null,
                        limit: null,
                        note: null,
                    },
                ]
            } else {
                console.error('POSTHOG_APP_CONTEXT or nested properties not found')
            }
        })

        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.locator('[data-attr="new-survey"]').click()
        await page.locator('[data-attr="new-blank-survey"]').click()
        await page.locator('[data-attr="survey-name"]').fill(name)

        // Prepare questions
        await page.locator('[data-attr=survey-question-label-0]').fill('How happy are you?')
        await expect(page.locator('[data-attr=survey-question-label-0]')).toHaveValue('How happy are you?')
        await page.locator('[data-attr=survey-question-type-0]').click()
        await page.locator('[data-attr=survey-question-type-0-rating]').click()
        await page.locator('[data-attr="add-question"]').click()

        await page.locator('[data-attr=survey-question-label-1]').fill('Sorry to hear that. Please tell us more!')
        await expect(page.locator('[data-attr=survey-question-label-1]')).toHaveValue(
            'Sorry to hear that. Please tell us more!'
        )
        await page.locator('[data-attr="add-question"]').click()

        await page
            .locator('[data-attr=survey-question-label-2]')
            .fill('Seems you are not completely happy. Please tell us more!')
        await expect(page.locator('[data-attr=survey-question-label-2]')).toHaveValue(
            'Seems you are not completely happy. Please tell us more!'
        )
        await page.locator('[data-attr="add-question"]').click()

        await page.locator('[data-attr=survey-question-label-3]').fill('Glad to hear that! Please tell us more')
        await expect(page.locator('[data-attr=survey-question-label-3]')).toHaveValue(
            'Glad to hear that! Please tell us more'
        )
        await page.locator('[data-attr="add-question"]').click()

        await page.locator('[data-attr=survey-question-label-4]').fill('Would you like to leave us a review?')
        await expect(page.locator('[data-attr=survey-question-label-4]')).toHaveValue(
            'Would you like to leave us a review?'
        )
        await page.locator('[data-attr=survey-question-type-4]').click()
        await page.locator('[data-attr=survey-question-type-4-single_choice]').click()
        await page.locator('[data-attr="add-question"]').click()

        await page.locator('[data-attr=survey-question-label-5]').fill('Please write your review here')
        await expect(page.locator('[data-attr=survey-question-label-5]')).toHaveValue('Please write your review here')

        // Helper function to reduce repetition when selecting from popovers
        const selectPopoverOption = async (triggerSelector: string, optionText: string): Promise<void> => {
            await page.locator(triggerSelector).click()
            await expect(page.locator('.Popover__box')).toBeVisible()
            await page.locator('.Popover__box button').getByText(optionText, { exact: true }).click()
            await expect(page.locator(triggerSelector)).toContainText(optionText)
        }

        // Set branching
        // Question 1 - How happy are you?
        await page.locator('[data-attr=survey-question-panel-0]').click()
        await expect(page.locator('button[data-attr="survey-question-0-branching-select"]')).toContainText(
            'Next question'
        )
        await selectPopoverOption(
            'button[data-attr="survey-question-0-branching-select"]',
            'Specific question based on answer'
        )
        await selectPopoverOption('[data-attr=survey-question-0-branching-response_based-select-0]', '2.')
        await selectPopoverOption('[data-attr=survey-question-0-branching-response_based-select-1]', '3.')
        await selectPopoverOption('[data-attr=survey-question-0-branching-response_based-select-2]', '4.')

        // Question 2 - Sorry to hear that...
        await page.locator('[data-attr=survey-question-panel-1]').click()
        await selectPopoverOption('[data-attr=survey-question-1-branching-select]', 'Confirmation message')

        // Question 3 - Seems you are not completely happy...
        await page.locator('[data-attr=survey-question-panel-2]').click()
        await selectPopoverOption('[data-attr=survey-question-2-branching-select]', 'Confirmation message')

        // Question 4 - Glad to hear that...
        await page.locator('[data-attr=survey-question-panel-3]').click()
        await selectPopoverOption('[data-attr=survey-question-3-branching-select]', '5.')

        // Question 5 - Would you like to leave us a review?
        await page.locator('[data-attr=survey-question-panel-4]').click()
        await selectPopoverOption('[data-attr=survey-question-4-branching-select]', 'Specific question based on answer')
        await selectPopoverOption('[data-attr=survey-question-4-branching-response_based-select-0]', 'Next question')
        await selectPopoverOption(
            '[data-attr=survey-question-4-branching-response_based-select-1]',
            'Confirmation message'
        )

        // Question 6 - Please write your review here
        await page.locator('[data-attr=survey-question-panel-5]').click()
        await expect(page.locator('button[data-attr="survey-question-5-branching-select"]')).toContainText(
            'Confirmation message'
        )

        // Save
        await page.locator('[data-attr="save-survey"]').nth(0).click()
        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')
    })

    // Additional tests will be converted here...
})
