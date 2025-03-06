import { AppContext, OrganizationType, UserType } from '~/types'

import { SurveysPage } from '../page-models/surveysPage'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Surveys', () => {
    let name: string

    test.beforeEach(async ({ page }) => {
        name = 'survey-' + Math.floor(Math.random() * 10000000)
        await page.goToMenuItem('surveys')
    })

    test('creates a new survey', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await new SurveysPage(page).createSurvey(name)

        // check preview release conditions
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users')

        await new SurveysPage(page).launchSurvey()

        // refresh -> see survey show up on page
        await page.reload()
        await expect(page.getByText('Unique user(s) shown')).toBeVisible()

        await new SurveysPage(page).stopSurvey()

        // back to surveys
        await page.goto('/surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        // back into survey
        await page.locator(`[data-row-key="${name}"] a`, { hasText: name }).click()

        // edit
        await new SurveysPage(page).editSurvey()

        // remove user targeting properties
        await page.click('.LemonCollapsePanel :text("Display conditions")')
        await page.click('text=Remove all property targeting')

        // save
        await page.locator('[data-attr="save-survey"]').nth(0).click()

        // check preview release conditions
        await page.locator('.LemonTabs >> text=Overview').click()
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toHaveCount(0)
    })

    test('deletes a survey', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await page.click('[data-attr=new-survey]')
        await page.click('[data-attr=new-blank-survey]')
        await page.fill('[data-attr=survey-name]', name)
        await page.locator('[data-attr=save-survey]').first().click()

        // after save there should be a launch button
        await expect(page.locator('button[data-attr="launch-survey"]')).toHaveText('Launch')

        await page.goto('/surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        // open the newly created survey
        await page.locator(`[data-row-key=${name}] a`, { hasText: name }).click()
        await page.click('.TopBar3000 [data-attr="more-button"]')
        await page.click('[data-attr=delete-survey]')

        // confirm deletion
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.locator('.LemonModal__layout')).toContainText('Delete this survey?')
        await page.getByRole('button', { name: 'Delete' }).click()
        await expect(page.locator('.Toastify__toast-body')).toContainText('Survey deleted')

        // verify survey is deleted by checking it's not in the table
        await expect(page.locator(`[data-row-key=${name}] a`, { hasText: name })).not.toBeVisible()
    })

    test('duplicates a survey', async ({ page }) => {
        await new SurveysPage(page).createSurvey(name)

        // Launch survey
        await new SurveysPage(page).launchSurvey()
        await page.getByTestId('toast-close-button').nth(0).click()

        // duplicate survey
        await page.click('.TopBar3000 [data-attr="more-button"]')
        await page.click('[data-attr=duplicate-survey]')

        // confirm duplication
        await expect(page.locator('[data-attr=success-toast]', { hasText: 'duplicated' })).toBeVisible()
        await page.getByRole('button', { name: 'View survey' }).click()

        await expect(page.locator('[data-attr=top-bar-name]')).toContainText(`${name} (copy)`)

        // ensure new copy is in draft
        await expect(page.locator('button[data-attr="launch-survey"]')).toHaveText('Launch')

        // check if targeting criteria is copied
        await expect(page.locator('text=Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users in this set.')

        // delete the duplicated survey
        await page.click('[data-attr=more-button]')
        await page.click('[data-attr=delete-survey]')
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.locator('.LemonModal__layout')).toContainText('Delete this survey?')
        await page.getByRole('button', { name: 'Delete' }).click()

        // Archive the original survey
        await page.goto('/surveys')
        await page.locator('[data-attr=surveys-table] a').locator(`[data-row-key="${name}"]`).click()
        await page.click('[data-attr=stop-survey]')
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.locator('.LemonModal__layout')).toContainText('Stop this survey?')
        await page.getByRole('button', { name: 'Stop' }).click()
        await page.click('.TopBar3000 [data-attr="more-button"]')
        await page.click('[data-attr=archive-survey]')
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.locator('.LemonModal__layout')).toContainText('Archive this survey?')
        await page.getByRole('button', { name: 'Archive' }).click()

        // check the duplicated survey is created with a draft state
        await page.click('[data-attr=more-button]')
        await page.click('[data-attr=duplicate-survey]')
        await page.goto('/surveys')
        await expect(
            page.locator('[data-attr=surveys-table]').locator(`[data-row-key="${name} (copy)"] >> [data-attr=status]`)
        ).toHaveText('DRAFT')
    })

    test('can set responses limit', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await page.click('[data-attr=new-survey]')
        await page.click('[data-attr=new-blank-survey]')
        await page.fill('[data-attr=survey-name]', name)

        // Set responses limit
        await page.click('.LemonCollapsePanel :text("Completion conditions")')
        await page.locator('[data-attr=survey-collection-until-limit]').first().click()
        await page.locator('[data-attr=survey-responses-limit-input]').fill('228')

        await page.locator('[data-attr=save-survey]').first().click()
        await expect(page.locator('button[data-attr="launch-survey"]')).toHaveText('Launch')

        await page.reload()
        await expect(page.locator('text=The survey will be stopped once 100228 responses are received.')).toBeVisible()
    })

    test('creates a new survey with branching logic', async ({ page }) => {
        // If you can set window context in your environment:
        // e.g. advanced features or direct script injection
        await page.addInitScript(() => {
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                current_user: {
                    ...(window.POSTHOG_APP_CONTEXT?.current_user || {}),
                    organization: {
                        ...window.POSTHOG_APP_CONTEXT?.current_user?.organization,
                        available_product_features: [
                            {
                                key: 'surveys_multiple_questions',
                                name: 'Multiple questions',
                                description: 'Ask up to 10 questions in a single survey.',
                                unit: null,
                                limit: null,
                                note: null,
                            },
                        ],
                    } as OrganizationType,
                } as UserType,
            } as AppContext
        })

        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.click('[data-attr="new-survey"]')
        await page.click('[data-attr="new-blank-survey"]')
        await page.fill('[data-attr="survey-name"]', name)

        // Prepare questions
        await page.fill('[data-attr=survey-question-label-0]', 'How happy are you?')
        await page.click('[data-attr=survey-question-type-0]')
        await page.click('[data-attr=survey-question-type-0-rating]')
        await page.click('[data-attr="add-question"]')

        await page.fill('[data-attr=survey-question-label-1]', 'Sorry to hear that. Please tell us more!')
        await page.click('[data-attr="add-question"]')

        await page.fill(
            '[data-attr=survey-question-label-2]',
            'Seems you are not completely happy. Please tell us more!'
        )
        await page.click('[data-attr="add-question"]')

        await page.fill('[data-attr=survey-question-label-3]', 'Glad to hear that! Please tell us more')
        await page.click('[data-attr="add-question"]')

        await page.fill('[data-attr=survey-question-label-4]', 'Would you like to leave us a review?')
        await page.click('[data-attr=survey-question-type-4]')
        await page.click('[data-attr=survey-question-type-4-single_choice]')
        await page.click('[data-attr="add-question"]')

        await page.fill('[data-attr=survey-question-label-5]', 'Please write your review here')

        // Set branching on question 0 => "Specific question based on answer"
        await page.locator('[data-attr=survey-question-panel-0]').click()
        await page.click('[data-attr="survey-question-0-branching-select"]')
        await page.locator('.Popover__box').getByText('Specific question based on answer').click()
        await page.click('[data-attr="survey-question-0-branching-response_based-select-0"]')
        await page.locator('.Popover__box').getByText('2.').click()
        await page.click('[data-attr="survey-question-0-branching-response_based-select-1"]')
        await page.locator('.Popover__box').getByText('3.').click()
        await page.click('[data-attr="survey-question-0-branching-response_based-select-2"]')
        await page.locator('.Popover__box').getByText('4.').click()

        // Q1 => "Confirmation message"
        await page.locator('[data-attr="survey-question-panel-1"]').click()
        await page.click('[data-attr="survey-question-1-branching-select"]')
        await page.locator('.Popover__box').getByText('Confirmation message').click()

        // Q2 => same
        await page.locator('[data-attr="survey-question-panel-2"]').click()
        await page.click('[data-attr="survey-question-2-branching-select"]')
        await page.locator('.Popover__box').getByText('Confirmation message').click()

        // Q3 => "Would you like to leave us a review?" => question 5
        await page.locator('[data-attr="survey-question-panel-3"]').click()
        await page.click('[data-attr="survey-question-3-branching-select"]')
        await page.locator('.Popover__box').getByText('5.').click()

        // Q4 => "Specific question based on answer"
        await page.locator('[data-attr="survey-question-panel-4"]').click()
        await page.click('[data-attr="survey-question-4-branching-select"]')
        await page.locator('.Popover__box').getByText('Specific question based on answer').click()
        await page.click('[data-attr="survey-question-4-branching-response_based-select-0"]')
        await page.locator('.Popover__box').getByText('Next question').click()
        await page.click('[data-attr="survey-question-4-branching-response_based-select-1"]')
        await page.locator('.Popover__box').getByText('Confirmation message').click()

        // Q5 => "Confirmation message" by default
        await page.locator('[data-attr="survey-question-panel-5"]').click()
        // no changes needed

        // Save
        await page.locator('[data-attr="save-survey"]').first().click()
        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')
    })
})
