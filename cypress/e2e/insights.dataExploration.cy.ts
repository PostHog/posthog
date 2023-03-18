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

    it('can open the query editor', () => {
        insight.newInsight('TRENDS', true)
        cy.get('[aria-label="Edit code"]').click()
        cy.get('[data-attr="query-editor"]').should('exist')
    })

    describe('opening a new insight', () => {
        it('can open a new trends insight', () => {
            insight.newInsight('TRENDS', true)
            cy.get('.trends-insights-container canvas').should('exist')
            cy.get('tr').should('have.length', 2)
        })

        it('can open a new funnels insight', () => {
            insight.newInsight('FUNNELS', true)
            cy.get('.funnels-empty-state__title').should('exist')
        })

        it('can open a new retention insight', () => {
            insight.newInsight('RETENTION', true)
            cy.get('.RetentionContainer canvas').should('exist')
            cy.get('.RetentionTable__Tab').should('have.length', 66)
        })

        it('can open a new paths insight', () => {
            insight.newInsight('PATHS', true)
            cy.get('.Paths g').should('have.length', 36)
        })

        it('can open a new stickiness insight', () => {
            insight.newInsight('STICKINESS', true)
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new lifecycle insight', () => {
            insight.newInsight('LIFECYCLE', true)
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new SQL insight', () => {
            insight.newInsight('SQL', true)
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length', 3)
        })

        it('can open a new JSON insight', () => {
            cy.intercept('POST', /api\/projects\/\d+\/query\//).as('query')

            insight.newInsight('JSON', true)
            cy.get('[data-attr="query-editor"]').should('exist')

            // the default JSON query doesn't have any results, switch to one that does

            // obviously we need to clear the text area multiple times
            cy.get('[data-attr="query-editor"] textarea').type('{selectall}')
            cy.get('[data-attr="query-editor"] textarea').type('{backspace}')
            cy.get('[data-attr="query-editor"] textarea').type('{selectall}')
            cy.get('[data-attr="query-editor"] textarea').type('{backspace}')
            cy.get('[data-attr="query-editor"] textarea').type('{selectall}')
            cy.get('[data-attr="query-editor"] textarea').type('{backspace}')
            cy.get('[data-attr="query-editor"] textarea').type('{selectall}')
            cy.get('[data-attr="query-editor"] textarea').type('{backspace}')

            cy.get('[data-attr="query-editor"] textarea').type(`
{
  "kind": "DataTableNode",
  "full": true,
  "source": {
    "kind": "EventsQuery",
    "select": [
      "count()"
    ]
  }
}`)

            // monaco adds closing squares and curlies as we type,
            // so, we need to delete any trailing characters to make valid JSON
            // 😡
            for (let i = 0; i < 10; i++) {
                cy.get('[data-attr="query-editor"] textarea').type('{del}')
            }

            cy.get('[data-attr="query-editor"] button').click()

            cy.wait('@query').then(() => {
                cy.get('tr.DataTable__row').should('have.length', 1)
            })
        })
    })

    it('can open a new SQL insight and navigate to a different one', () => {
        /**
         * This is here as a regression test. We had a bug where navigating to a new query based insight
         * and then to a new filter based insight, would briefly start loading the filter based insight
         * and then jump back to the query based insight.
         */
        insight.newInsight('SQL', true)
        cy.get('[data-attr="hogql-query-editor"]').should('exist')
        cy.get('tr.DataTable__row').should('have.length', 3)

        cy.get('a[data-attr="insight-retention-tab"]').click()
        cy.get('[data-attr="hogql-query-editor"]').should('not.exist')

        cy.get('[data-attr="retention-table"] .RetentionTable__Tab').should('have.length', 66)
    })
})
