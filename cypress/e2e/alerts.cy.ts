import { createInsight, insight, savedInsights } from '../productAnalytics'
import { decideResponse } from '../fixtures/api/decide'

describe('Alerts', () => {
    it('Should allow create and delete an alert', () => {
        cy.intercept('**/decide/*', (req) =>
            req.reply(
                decideResponse({
                    alerts: true,
                })
            )
        )
        createInsight('insight')
        cy.get('[data-attr=insight-header-more]').click()
        // Alerts should be disabled for trends represented with graphs
        cy.get('[data-attr=disabled-alerts-button]').should('exist')

        // Only the Number representation supports alerts, so change the insight
        cy.get('[data-attr=insight-edit-button]').click()
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Number').click()
        cy.get('[data-attr=insight-save-button]').contains('Save').click()
        cy.url().should('not.include', '/edit')

        cy.get('[data-attr=insight-header-more]').click()
        cy.contains('Alerts').click()
        cy.contains('New alert').click()

        cy.get('[data-attr=alert-name]').clear().type('Alert name')
        cy.get('[data-attr=alert-notification-targets').clear().type('a@b.c')
        cy.get('[data-attr=alert-lower-threshold').clear().type('100')
        cy.get('[data-attr=alert-upper-threshold').clear().type('200')
        cy.contains('Create alert').click()
        cy.url().should('not.include', '/new')

        cy.get('[aria-label="close"]').click()
        cy.reload()

        // Check the alert has the same values as when it was created
        cy.get('[data-attr=insight-header-more]').click()
        cy.contains('Alerts').click()
        cy.contains('Manage alerts').click()
        cy.get('[data-attr=alert-list-item]').contains('Alert name').click()
        cy.get('[data-attr=alert-notification-targets]').should('have.value', 'a@b.c')
        cy.get('[data-attr=alert-name]').should('have.value', 'Alert name')
        cy.get('[data-attr=alert-lower-threshold').should('have.value', '100')
        cy.get('[data-attr=alert-upper-threshold').should('have.value', '200')
        cy.contains('Delete alert').click()

        cy.reload()
        cy.contains('Alert name').should('not.exist')
    })
})
