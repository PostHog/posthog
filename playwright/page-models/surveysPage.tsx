import { Page } from '@playwright/test'

import { expect } from '../utils/playwright-test-base'

export class SurveysPage {
    constructor(private readonly page: Page) {}

    async createSurvey(name: string): Promise<void> {
        // click via top right button
        await this.page.click('[data-attr="new-survey"]')
        await this.page.click('[data-attr="new-blank-survey"]')

        // fill out a rating survey
        await this.page.fill('[data-attr="survey-name"]', name)
        await this.page.click('[data-attr="survey-question-type-0"]')
        await this.page.click('text=Rating')

        // check defaults
        await expect(
            this.page.getByTestId('survey-question-panel-0').getByRole('button', { name: 'Question 1. How likely are' })
        ).toHaveText(/How likely are you to recommend/)
        await expect(
            this.page.locator('#scenes\\.surveys\\.surveyLogic\\.new\\.survey\\.questions\\.0\\.scale')
        ).toContainText('0 - 10')
        await expect(
            this.page.locator('#scenes\\.surveys\\.surveyLogic\\.new\\.survey\\.questions\\.0\\.upperBoundLabel')
        ).toHaveValue('Very likely')

        // change the scale to 1 - 5
        await this.page.click('#scenes\\.surveys\\.surveyLogic\\.new\\.survey\\.questions\\.0\\.scale')
        await this.page.click('text=1 - 5')
        await expect(
            this.page.locator('#scenes\\.surveys\\.surveyLogic\\.new\\.survey\\.questions\\.0\\.scale')
        ).toContainText('1 - 5')

        // ensure the preview is updated
        await expect(this.page.locator('.survey-form')).toContainText('How likely are you to recommend us to a friend?')
        await expect(this.page.locator('.survey-form')).toContainText('Unlikely')
        await expect(this.page.locator('.survey-form')).toContainText('Very likely')
        await expect(this.page.locator('.survey-form .ratings-number')).toHaveCount(5)

        // add targeting filters
        await this.page.click('.LemonCollapsePanel :text("Display conditions")')
        await this.page.click('text=All users')
        await this.page.click('.Popover__content >> text=Users who match')
        await this.page.click('text=Add property targeting')
        await this.page.click('[data-attr="property-select-toggle-0"]')
        await this.page.click('[data-attr="prop-filter-person_properties-0"]')
        // in Cypress we do .focus().type().type('{enter}'); in Playwright:
        await this.page.locator('[data-attr="prop-val"]').nth(1).fill('true')
        await this.page.locator('[data-attr="prop-val"]').nth(1).press('Enter')
        await this.page.click('[data-attr="rollout-percentage"]')
        await this.page.fill('[data-attr="rollout-percentage"]', '50')

        // save
        await this.page.locator('[data-attr="save-survey"]').nth(0).click()
        await expect(this.page.locator('[data-attr="success-toast"]')).toContainText('created')
    }

    async launchSurvey(): Promise<void> {
        await this.page.click('[data-attr="launch-survey"]')
        await expect(this.page.locator('.LemonModal__layout')).toBeVisible()
        await expect(this.page.locator('.LemonModal__layout')).toContainText('Launch this survey?')
        await this.page.getByRole('button', { name: 'Launch' }).click()
    }

    async stopSurvey(): Promise<void> {
        await this.page.click('text=Stop')
        await expect(this.page.locator('.LemonModal__layout')).toBeVisible()
        await expect(this.page.locator('.LemonModal__layout')).toContainText('Stop this survey?')
        await this.page.getByRole('button', { name: 'Stop' }).click()
    }

    async editSurvey(): Promise<void> {
        await this.page.click('.TopBar3000 [data-attr="more-button"]')
        await expect(this.page.locator('.Popover__content')).toBeVisible()
        await this.page.locator('.Popover__content').getByText('Edit').click()
    }
}
