import { urls } from 'scenes/urls'
import { randomString } from '../support/random'
import { insight } from '../productAnalytics'
import { decideResponse } from '../fixtures/api/decide'

// For tests related to trends please check trendsElements.js
describe('Insights (with data exploration on)', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'data-exploration-query-tab': true,
                    'data-exploration-insights': true,
                })
            )
        )
        cy.visit(urls.insightNew())
    })

    it('shows the edit as json button', () => {
        const insightName = randomString('insight-name-')
        insight.create(insightName, 'TRENDS', true)
    })
})
