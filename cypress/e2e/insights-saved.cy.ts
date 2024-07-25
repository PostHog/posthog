import { urls } from 'scenes/urls'

import { createInsight } from '../productAnalytics'

chai.Assertion.addMethod('neverHaveChild', function (childSelector) {
    this._obj.on('DOMNodeInserted', () => {
        const matchCount = cy.$$(childSelector, this._obj).length
        if (matchCount > 0) {
            throw new Error(
                `Expected element to never have child ${childSelector}, but found ${matchCount} match${
                    matchCount > 1 ? 'es' : ''
                }`
            )
        }
    })
})

// For tests related to trends please check trendsElements.js
// insight tests were split up because Cypress was struggling with this many tests in one file🙈
describe('Insights - saved', () => {
    it('Data is available immediately', () => {
        void createInsight('saved insight').then((newInsightId) => {
            cy.get('[data-attr=trend-line-graph]').should('exist') // Results cached
            cy.visit(urls.insightView(newInsightId)) // Full refresh
            cy.get('.InsightViz').should('exist').should('neverHaveChild', '.insight-empty-state') // Only cached data
            cy.get('[data-attr=trend-line-graph]').should('exist')
        })
    })

    it('If cache empty, initiate async refresh', () => {
        cy.intercept('GET', /\/api\/projects\/\d+\/insights\/?\?[^/]*?refresh=async/).as('getInsightsRefreshAsync')
        let newInsightId: string
        void createInsight('saved insight').then((insightId) => {
            newInsightId = insightId
        })
        cy.task('resetInsightCache').then(() => {
            cy.visit(urls.insightView(newInsightId)) // Full refresh
            cy.get('.insight-empty-state').should('exist') // There should be a loading state for a moment
            cy.wait('@getInsightsRefreshAsync').then(() => {
                cy.get('[data-attr=trend-line-graph]').should('exist')
            })
        })
    })
})
