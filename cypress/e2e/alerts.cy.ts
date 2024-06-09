import { createInsight } from '../productAnalytics'
import { decideResponse } from '../fixtures/api/decide'

describe('Alerts', () => {
    beforeEach(() => {
        cy.intercept('**/decide/*', (req) =>
            req.reply(
                decideResponse({
                    alerts: true,
                })
            )
        )
        createInsight('insight')
    })

    const createAlert = (
        name: string = 'Alert name',
        email: string = 'a@b.c',
        lowerThreshold: string = '100',
        upperThreshold: string = '200'
    ): void => {
        cy.get('[data-attr=more-button]').click()
        cy.contains('Alerts').click()
        cy.contains('New alert').click()

        cy.get('[data-attr=alert-name]').clear().type(name)
        cy.get('[data-attr=alert-notification-targets').clear().type(email)
        cy.get('[data-attr=alert-lower-threshold').clear().type(lowerThreshold)
        cy.get('[data-attr=alert-upper-threshold').clear().type(upperThreshold)
        cy.contains('Create alert').click()
        cy.url().should('not.include', '/new')

        cy.get('[aria-label="close"]').click()
    }

    const setInsightDisplayType = (displayType: string = 'Number'): void => {
        // Only the Number representation supports alerts, so change the insight
        cy.get('[data-attr=insight-edit-button]').click()
        cy.get('[data-attr=chart-filter]').click()
        cy.contains(displayType).click()
        cy.get('[data-attr=insight-save-button]').contains('Save').click()
        cy.url().should('not.include', '/edit')
    }

    it('Should allow create and delete an alert', () => {
        cy.get('[data-attr=more-button]').click()
        // Alerts should be disabled for trends represented with graphs
        cy.get('[data-attr=disabled-alerts-button]').should('exist')

        setInsightDisplayType()

        createAlert()
        cy.reload()

        // Check the alert has the same values as when it was created
        cy.get('[data-attr=more-button]').click()
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

    it('Should warn about an alert deletion', () => {
        setInsightDisplayType('Number')

        createAlert()

        cy.get('[data-attr=insight-edit-button]').click()
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Line chart').click()

        cy.contains('the existing alerts will be deleted').should('exist')

        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Number').click()

        cy.contains('the existing alerts will be deleted').should('not.exist')
    })
})
