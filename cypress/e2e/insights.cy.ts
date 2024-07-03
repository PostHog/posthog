import { urls } from 'scenes/urls'
import { createInsight, insight, savedInsights } from '../productAnalytics'
import { randomString } from '../support/random'

// For tests related to trends please check trendsElements.js
// insight tests were split up because Cypress was struggling with this many tests in one file🙈
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    it('Can change insight name', () => {
        const startingName = randomString('starting-value-')
        const editedName = randomString('edited-value-')
        createInsight(startingName)
        cy.get('[data-attr="top-bar-name"]').should('contain', startingName)

        cy.get('[data-attr="top-bar-name"] button').click()
        cy.get('[data-attr="top-bar-name"] input').clear().type(editedName)
        cy.get('[data-attr="top-bar-name"] [title="Save"]').click()

        cy.get('[data-attr="top-bar-name"]').should('contain', editedName)

        savedInsights.checkInsightIsInListView(editedName)
    })

    it('Can undo a change of insight name', () => {
        createInsight('starting value')
        cy.get('[data-attr="top-bar-name"]').should('contain', 'starting value')

        cy.get('[data-attr="top-bar-name"] button').click({ force: true })
        cy.get('[data-attr="top-bar-name"] input').clear().type('edited value')
        cy.get('[data-attr="top-bar-name"] [title="Save"]').click()

        cy.get('[data-attr="top-bar-name"]').should('contain', 'edited value')

        cy.get('[data-attr="edit-insight-undo"]').click()

        cy.get('[data-attr="top-bar-name"]').should('not.contain', 'edited value')
        cy.get('[data-attr="top-bar-name"]').should('contain', 'starting value')

        savedInsights.checkInsightIsInListView('starting value')
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
        cy.visit('/activity/explore/') // Should work with trailing slash just like without it
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
})
