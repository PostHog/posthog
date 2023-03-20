import { urls } from 'scenes/urls'
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
        insight.newInsight('TRENDS', true)
    })

    it('can shows the query editor', () => {
        insight.newInsight('TRENDS', true)
        cy.get('[aria-label="Edit code"]').click()
        cy.get('[data-attr="query-editor"]').should('exist')
    })

    it('can edit an insight using the query editor', () => {
        insight.newInsight('TRENDS', true)
        cy.get('[aria-label="Edit code"]').click()
        cy.get('[data-attr="query-editor"]').should('exist')
    })
})
