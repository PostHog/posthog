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

    describe('opening a new insight directly', () => {
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

            insight.updateQueryEditorText(`
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

            cy.wait('@query').then(() => {
                cy.get('tr.DataTable__row').should('have.length', 1)
            })
        })
    })

    describe('opening a new insight after opening a new SQL insight', () => {
        // ugh, these tests have identical assertions to the ones above, but we need to open a SQL insight first
        // and then click a different tab to switch to that insight.
        // this is because we had a bug where doing that would mean after starting to load the new insight,
        // the SQL insight would be unexpectedly re-selected and the page would switch back to it

        beforeEach(() => {
            insight.newInsight('SQL', true)
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length', 3)
        })

        it('can open a new trends insight', () => {
            insight.clickTab('TRENDS')
            cy.get('.trends-insights-container canvas').should('exist')
            cy.get('tr').should('have.length', 2)
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
            cy.get('.Paths g').should('have.length', 36)
        })

        it('can open a new stickiness insight', () => {
            insight.clickTab('STICKINESS')
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new lifecycle insight', () => {
            insight.clickTab('LIFECYCLE')
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new SQL insight', () => {
            insight.clickTab('SQL')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length', 3)
        })

        it('can open a new JSON insight', () => {
            cy.intercept('POST', /api\/projects\/\d+\/query\//).as('query')

            insight.clickTab('JSON')
            cy.get('[data-attr="query-editor"]').should('exist')

            insight.updateQueryEditorText(`
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

            cy.wait('@query').then(() => {
                cy.get('tr.DataTable__row').should('have.length', 1)
            })
        })
    })

    it('can open a new SQL insight and navigate to a different one, then back to SQL, and back again', () => {
        /**
         * This is here as a regression test. We had a bug where navigating to a new query based insight,
         * then clicking on the trends tab, then on SQL, and again on trends would mean that the trends
         * tab would be selected, but no data loaded for it 🤷‍♀️
         */

        insight.newInsight('SQL', true)
        cy.get('[data-attr="hogql-query-editor"]').should('exist')
        cy.get('tr.DataTable__row').should('have.length', 3)

        insight.clickTab('TRENDS')
        cy.get('.trends-insights-container canvas').should('exist')
        cy.get('tr').should('have.length', 2)
        cy.contains('tr', 'No insight results').should('not.exist')

        insight.clickTab('SQL')
        cy.get('[data-attr="hogql-query-editor"]').should('exist')
        cy.get('tr.DataTable__row').should('have.length', 3)

        insight.clickTab('TRENDS')
        cy.get('.trends-insights-container canvas').should('exist')
        cy.get('tr').should('have.length', 2)
        cy.contains('tr', 'No insight results').should('not.exist')
    })
})
