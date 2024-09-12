import { urls } from 'scenes/urls'

import { insight } from '../productAnalytics'
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
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    describe('navigation', () => {
        it('can save and load and edit a SQL insight', () => {
            insight.newInsight('SQL')
            const insightName = randomString('SQL insight')
            insight.editName(insightName)
            insight.save()
            cy.visit(urls.savedInsights())

            // load the named insight
            cy.contains('.saved-insights tr', insightName).within(() => {
                cy.get('.Link').click()
            })

            cy.get('[data-attr="hogql-query-editor"]').should('not.exist')
            cy.get('tr.DataVizRow').should('have.length.gte', 2)

            cy.get('[data-attr="insight-edit-button"]').click()
            cy.wait(2000)

            insight.clickTab('RETENTION')

            cy.wait(2000)
            cy.get('[data-attr="insight-save-button"]').click()

            cy.get('.RetentionContainer canvas').should('exist')
            cy.get('.RetentionTable__Tab').should('have.length', 66)
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

            cy.get('.DataVizRow').should('have.length.gte', 2)

            insight.clickTab('TRENDS')
            cy.get('.TrendsInsight canvas').should('exist')
            cy.get('tr').should('have.length.gte', 2)
            cy.contains('tr', 'No insight results').should('not.exist')

            insight.clickTab('SQL')
            cy.get('[data-attr="hogql-query-editor"]').should('exist')
            insight.updateQueryEditorText(hogQLQuery, 'hogql-query-editor')

            cy.get('.DataVizRow').should('have.length.gte', 2)

            insight.clickTab('TRENDS')
            cy.get('.TrendsInsight canvas').should('exist')
            cy.get('tr').should('have.length.gte', 2)
            cy.contains('tr', 'No insight results').should('not.exist')
        })

        it('can open event explorer as an insight', () => {
            cy.clickNavMenu('activity')
            cy.get('[data-attr="open-json-editor-button"]').click()
            cy.get('[data-attr="insight-json-tab"]').should('exist')
        })

        it('does not show the json tab usually', () => {
            cy.clickNavMenu('savedinsights')
            cy.get('[data-attr="insight-json-tab"]').should('not.exist')
        })
    })
})
