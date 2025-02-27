import { urls } from 'scenes/urls'

import { createInsight } from '../productAnalytics'

// For tests related to trends please check trendsElements.js
// insight tests were split up because Cypress was struggling with this many tests in one file🙈
describe('Insights - saved', () => {
    it('If cache empty, initiate async refresh', () => {
        cy.intercept('GET', /\/api\/environments\/\d+\/insights\/?\?[^/]*?refresh=async/).as('getInsightsRefreshAsync')
        let newInsightId: string
        createInsight('saved insight').then((insightId) => {
            newInsightId = insightId
        })
        cy.task('resetInsightCache').then(() => {
            cy.visit(urls.insightView(newInsightId)) // Full refresh

            cy.get('[data-attr="insight-empty-state"]').should('exist') // There should be a loading state for a moment
            cy.wait('@getInsightsRefreshAsync').then(() => {
                cy.get('[data-attr=trend-line-graph]').should('exist')
            })
        })
    })
})
