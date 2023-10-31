describe('Billing', () => {
    beforeEach(() => {
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })

        cy.visit('/organization/billing')
    })

    it('Show unsubscribe survey', () => {
        cy.intercept('/api/billing-v2/deactivate?products=product_analytics', {
            fixture: 'api/billing-v2/billing-v2-unsubscribed.json',
        })
        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal__header').should('contain', "Let us know why you're unsubscribing")
        cy.contains('.LemonModal .LemonButton', 'Unsubscribe').click()
    })
})
