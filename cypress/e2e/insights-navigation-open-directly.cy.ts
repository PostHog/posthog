import { urls } from 'scenes/urls'

import { insight } from '../productAnalytics'

const hogQLQuery = `select event,
          count()
     from events
 group by event,
          properties.$browser,
          person.properties.email
 order by count() desc
    limit 2`

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
                cy.get('.funnels-empty-state__title').should('exist')
            })

            it.skip('can open a new retention insight', () => {
                insight.newInsight('RETENTION')
                cy.get('.RetentionContainer canvas').should('exist')
                cy.get('.RetentionTable__Tab').should('have.length', 66)
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

            it('can open a new SQL insight', () => {
                insight.newInsight('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataVizRow').should('have.length.gte', 2)
            })
        })
    })
})
