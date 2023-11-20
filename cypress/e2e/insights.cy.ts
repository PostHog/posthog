import { urls } from 'scenes/urls'
import { randomString } from '../support/random'
import { decideResponse } from '../fixtures/api/decide'
import { savedInsights, createInsight, insight } from '../productAnalytics'

// For tests related to trends please check trendsElements.js
// insight tests were split up because Cypress was struggling with this many tests in one file🙈
describe('Insights', () => {
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

    it('Saving an insight sets breadcrumbs', () => {
        createInsight('insight name')

        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Product analytics')
        cy.get('[data-attr=breadcrumb-3]').should('have.text', 'insight name')
    })

    it('Can change insight name', () => {
        const startingName = randomString('starting-value-')
        const editedName = randomString('edited-value-')
        createInsight(startingName)
        cy.get('[data-attr="insight-name"]').should('contain', startingName)

        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
        cy.get('[data-attr="insight-name"] input').type(editedName)
        cy.get('[data-attr="insight-name"] [title="Save"]').click()

        cy.get('[data-attr="insight-name"]').should('contain', editedName)

        savedInsights.checkInsightIsInListView(editedName)
    })

    it('Can undo a change of insight name', () => {
        createInsight('starting value')
        cy.get('[data-attr="insight-name"]').should('contain', 'starting value')

        cy.get('[data-attr="insight-name"]').scrollIntoView()
        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click({ force: true })
        cy.get('[data-attr="insight-name"] input').type('edited value')
        cy.get('[data-attr="insight-name"] [title="Save"]').click()

        cy.get('[data-attr="insight-name"]').should('contain', 'edited value')

        cy.get('[data-attr="edit-insight-undo"]').click()

        cy.get('[data-attr="insight-name"]').should('not.contain', 'edited value')
        cy.get('[data-attr="insight-name"]').should('contain', 'starting value')

        savedInsights.checkInsightIsInListView('starting value')
    })

    it('Create new insight and save and continue editing', () => {
        cy.intercept('PATCH', /\/api\/projects\/\d+\/insights\/\d+\/?/).as('patchInsight')

        const insightName = randomString('insight-name-')
        createInsight(insightName)

        cy.get('[data-attr="insight-edit-button"]').click()

        cy.url().should('match', /insights\/[\w\d]+\/edit/)

        cy.get('.page-title').then(($pageTitle) => {
            const pageTitle = $pageTitle.text()

            cy.get('[data-attr="add-action-event-button"]').click()
            cy.get('[data-attr="trend-element-subject-1"]').click()
            cy.get('[data-attr="prop-filter-events-0"]').click()
            cy.get('[data-attr="insight-save-dropdown"]').click()
            cy.get('[data-attr="insight-save-and-continue"]').click()
            cy.wait('@patchInsight')
            // still on the insight edit page
            expect(pageTitle).to.eq($pageTitle.text())
            cy.get('[data-attr="insight-save-button"]').should('exist')
        })

        savedInsights.checkInsightIsInListView(insightName)
    })

    it('Shows not found error with invalid short URL', () => {
        cy.visit('/i/i_dont_exist')
        cy.location('pathname').should('eq', '/insights/i_dont_exist')
        cy.get('.LemonSkeleton').should('exist')
    })

    it('Stickiness graph', () => {
        cy.get('[role=tab]').contains('Stickiness').click()
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
    })

    it('Lifecycle graph', () => {
        cy.get('[data-attr=trend-line-graph]').should('exist') // Wait until components are loaded
        cy.get('[role=tab]').contains('Lifecycle').click()
        cy.get('div').contains('Lifecycle Toggles').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
        cy.get('[data-attr=add-action-event-button]').should('not.exist') // Can't add multiple series
    })

    it('Loads default filters correctly', () => {
        // Test that default params are set correctly even if the app doesn't start on insights
        cy.visit('/events/') // Should work with trailing slash just like without it
        cy.reload()

        cy.clickNavMenu('insight')
        cy.get('[data-attr="menu-item-insight"]').click()
        cy.get('[data-attr=trend-element-subject-0] span').should('contain', 'Pageview')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Cannot see tags or description (non-FOSS feature)', () => {
        cy.get('.insight-description').should('not.exist')
        cy.get('[data-attr=insight-tags]').should('not.exist')
    })

    describe('view source', () => {
        it('can open the query editor', () => {
            insight.newInsight('TRENDS')
            insight.save()
            cy.get('[data-attr="more-button"]').click()
            cy.get('[data-attr="show-insight-source"]').click()
            cy.get('[data-attr="query-editor"]').should('exist')
        })
    })
})
