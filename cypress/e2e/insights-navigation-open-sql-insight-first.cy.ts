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
        describe('opening a new insight after opening a new SQL insight', () => {
            // TRICKY: these tests have identical assertions to the ones above, but we need to open a SQL insight first
            // and then click a different tab to switch to that insight.
            // this is because we had a bug where doing that would mean after starting to load the new insight,
            // the SQL insight would be unexpectedly re-selected and the page would switch back to it

            beforeEach(() => {
                insight.newInsight('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataVizRow').should('have.length.gte', 2)
            })

            it('can open a new trends insight', () => {
                insight.clickTab('TRENDS')
                cy.get('.TrendsInsight canvas').should('exist')
                cy.get('tr').should('have.length.gte', 2)
                cy.contains('tr', 'No insight results').should('not.exist')
            })

            it('can open a new funnels insight', () => {
                insight.clickTab('FUNNELS')
                cy.get('.funnels-empty-state__title').should('exist')
            })

            it('can open a new retention insight', () => {
                insight.clickTab('RETENTION')
                cy.get('.RetentionContainer canvas').should('exist')
                cy.get('.RetentionTable__Tab').should('have.length', 66)
            })

            it('can open a new paths insight', () => {
                insight.clickTab('PATH')
                cy.get('.Paths g').should('have.length.gte', 5) // not a fixed value unfortunately
            })

            it('can open a new stickiness insight', () => {
                insight.clickTab('STICKINESS')
                cy.get('.TrendsInsight canvas').should('exist')
            })

            it('can open a new lifecycle insight', () => {
                insight.clickTab('LIFECYCLE')
                cy.get('.TrendsInsight canvas').should('exist')
            })

            it('can open a new SQL insight', () => {
                insight.clickTab('SQL')
                insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
                cy.get('[data-attr="hogql-query-editor"]').should('exist')
                cy.get('tr.DataVizRow').should('have.length.gte', 2)
            })
        })
    })
})
