import { urls } from 'scenes/urls'
import { insight } from '../productAnalytics'
import { decideResponse } from '../fixtures/api/decide'
import { randomString } from '../support/random'

const hogQLQuery = `select event,
          count()
     from events
 group by event,
          properties.$browser,
          person.properties.email
 order by count() desc
    limit 2`

// For tests related to trends please check trendsElements.js
describe('Insights (with data exploration on)', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    hogql: true,
                    'data-exploration-insights': true,
                })
            )
        )

        cy.visit(urls.insightNew())
    })

    it('can open the query editor', () => {
        insight.newInsight('TRENDS')
        cy.get('[aria-label="Edit as JSON"]').click()
        cy.get('[data-attr="query-editor"]').should('exist')
    })

    it('can save and load and edit a SQL insight', () => {
        insight.newInsight('SQL')
        const insightName = randomString('SQL insight')
        insight.editName(insightName)
        insight.save()
        cy.visit(urls.savedInsights())
        cy.contains('.row-name a', insightName).click()

        cy.get('[data-attr="hogql-query-editor"]').should('not.exist')
        cy.get('tr.DataTable__row').should('have.length.gte', 2)

        cy.get('[data-attr="insight-edit-button"]').click()
        insight.clickTab('RETENTION')

        cy.get('[data-attr="insight-save-button"]').click()

        cy.get('.RetentionContainer canvas').should('exist')
        cy.get('.RetentionTable__Tab').should('have.length', 66)
    })

    describe('opening a new insight directly', () => {
        it('can open a new trends insight', () => {
            insight.newInsight('TRENDS')
            cy.get('.trends-insights-container canvas').should('exist')
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
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new lifecycle insight', () => {
            insight.newInsight('LIFECYCLE')
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new SQL insight', () => {
            insight.newInsight('SQL')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length.gte', 2)
        })
    })

    describe('opening a new insight after opening a new SQL insight', () => {
        // TRICKY: these tests have identical assertions to the ones above, but we need to open a SQL insight first
        // and then click a different tab to switch to that insight.
        // this is because we had a bug where doing that would mean after starting to load the new insight,
        // the SQL insight would be unexpectedly re-selected and the page would switch back to it

        beforeEach(() => {
            insight.newInsight('SQL')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length.gte', 2)
        })

        it('can open a new trends insight', () => {
            insight.clickTab('TRENDS')
            cy.get('.trends-insights-container canvas').should('exist')
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
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new lifecycle insight', () => {
            insight.clickTab('LIFECYCLE')
            cy.get('.trends-insights-container canvas').should('exist')
        })

        it('can open a new SQL insight', () => {
            insight.clickTab('SQL')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            cy.get('tr.DataTable__row').should('have.length.gte', 2)
        })
    })

    it('can open a new SQL insight and navigate to a different one, then back to SQL, and back again', () => {
        /**
         * This is here as a regression test. We had a bug where navigating to a new query based insight,
         * then clicking on the trends tab, then on SQL, and again on trends would mean that the trends
         * tab would be selected, but no data loaded for it 🤷‍♀️
         */

        insight.newInsight('SQL')
        cy.get('[data-attr="hogql-query-editor"]').should('exist')
        insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')

        cy.get('.DataTable tr').should('have.length.gte', 2)

        insight.clickTab('TRENDS')
        cy.get('.trends-insights-container canvas').should('exist')
        cy.get('tr').should('have.length.gte', 2)
        cy.contains('tr', 'No insight results').should('not.exist')

        insight.clickTab('SQL')
        cy.get('[data-attr="hogql-query-editor"]').should('exist')
        insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')

        cy.get('.DataTable tr').should('have.length.gte', 2)

        insight.clickTab('TRENDS')
        cy.get('.trends-insights-container canvas').should('exist')
        cy.get('tr').should('have.length.gte', 2)
        cy.contains('tr', 'No insight results').should('not.exist')
    })

    it('can open event explorer as an insight', () => {
        cy.clickNavMenu('events')
        cy.get('[data-attr="open-json-editor-button"]').click()
        cy.get('[data-attr="insight-json-tab"]').should('exist')
    })

    it('does not show the json tab usually', () => {
        cy.clickNavMenu('savedinsights')
        cy.get('[data-attr="insight-json-tab"]').should('not.exist')
    })
})
