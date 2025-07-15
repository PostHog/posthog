import { urls } from 'scenes/urls'

import { insight } from '../productAnalytics'

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    describe('navigation', () => {
        describe('opening a new insight directly', () => {
            it('can open a new trends insight', () => {
                insight.newInsight('TRENDS')
                cy.get('.TrendsInsight canvas').should('exist')
                cy.get('tr').should('have.length.gte', 2)
            })

            it('can open a new funnels insight', () => {
                insight.newInsight('FUNNELS')
                cy.get('[data-attr="insight-empty-state"]').find('h2').should('exist')
            })

            it('can open a new paths insight', () => {
                insight.newInsight('PATHS')
                cy.get('.Paths g').should('have.length.gte', 5) // not a fixed value unfortunately
            })

            it('can open a new stickiness insight', () => {
                insight.newInsight('STICKINESS')
                cy.get('.TrendsInsight canvas').should('exist')
            })

            it('can open a new lifecycle insight', () => {
                insight.newInsight('LIFECYCLE')
                cy.get('.TrendsInsight canvas').should('exist')
            })
        })
    })
})
