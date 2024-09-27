import { decideResponse } from '../fixtures/api/decide'
import { createInsight } from '../productAnalytics'

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
        lowerThreshold: string = '100',
        upperThreshold: string = '200'
    ): void => {
        cy.get('[data-attr=more-button]').click()
        cy.contains('Manage alerts').click()
        cy.contains('New alert').click()

        cy.get('[data-attr=alertForm-name]').clear().type(name)
        cy.get('[data-attr=subscribed-users').click().type('{downarrow}{enter}')
        cy.get('[data-attr=alertForm-lower-threshold').clear().type(lowerThreshold)
        cy.get('[data-attr=alertForm-upper-threshold').clear().type(upperThreshold)
        cy.contains('Create alert').click()
        cy.get('.Toastify__toast-body').should('contain', 'Alert created.')
        cy.url().should('not.include', '/new')

        cy.contains('span', 'Close').click()
    }

    const setInsightDisplayTypeAndSave = (displayType: string): void => {
        // Only the Number representation supports alerts, so change the insight
        cy.get('[data-attr=insight-edit-button]').click()
        cy.get('[data-attr=chart-filter]').click()
        cy.contains(displayType).click()
        cy.get('.insight-empty-state').should('not.exist')
        cy.get('[data-attr=insight-save-button]').contains('Save').click()
        cy.url().should('not.include', '/edit')
    }

    it('Should allow create and delete an alert', () => {
        cy.get('[data-attr=more-button]').click()
        // Alerts should be disabled for trends represented with graphs
        cy.get('[data-attr=manage-alerts-button]').should('have.attr', 'aria-disabled', 'true')

        setInsightDisplayTypeAndSave('Number')

        createAlert()
        cy.reload()

        // Check the alert has the same values as when it was created
        cy.get('[data-attr=more-button]').click()
        cy.contains('Manage alerts').click()
        cy.get('[data-attr=alert-list-item]').contains('Alert name').click()
        cy.get('[data-attr=alertForm-name]').should('have.value', 'Alert name')
        cy.get('[data-attr=alertForm-lower-threshold').should('have.value', '100')
        cy.get('[data-attr=alertForm-upper-threshold').should('have.value', '200')
        cy.contains('Delete alert').click()
        cy.wait(2000)

        cy.reload()
        cy.contains('Alert name').should('not.exist')
    })

    it('Should warn about an alert deletion', () => {
        setInsightDisplayTypeAndSave('Number')

        createAlert('Alert to be deleted because of a changed insight')

        cy.get('[data-attr=insight-edit-button]').click()
        cy.contains('span', 'Funnels').click()

        cy.contains('the existing alerts will be deleted').should('exist')

        // Assert that reverting the display type removes the banner
        cy.contains('span', 'Trends').click()
        cy.contains('the existing alerts will be deleted').should('not.exist')

        // Assert that saving an insight in an incompatible state removes alerts
        cy.contains('span', 'Funnels').click()
        cy.get('[data-attr=insight-save-button]').contains('Save').click()

        cy.get('[data-attr=more-button]').click()
        cy.contains('Manage alerts').click()
        cy.contains('Alert to be deleted because of a changed insight').should('not.exist')
    })
})
