describe('Billing', () => {
    beforeEach(() => {
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })

        cy.visit('/organization/billing')
    })

    it('Show and submit unsubscribe survey', () => {
        cy.intercept('/api/billing-v2/deactivate?products=product_analytics', {
            fixture: 'api/billing-v2/billing-v2-unsubscribed-product-analytics.json',
        }).as('unsubscribeProductAnalytics')
        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal__content h3').should(
            'contain',
            'Why are you unsubscribing from Product analytics + data stack?'
        )
        cy.contains('.LemonModal .LemonButton', 'Unsubscribe').click()

        cy.get('.LemonModal').should('not.exist')
        cy.wait(['@unsubscribeProductAnalytics'])
    })

    it('Unsubscribe survey text area maintains unique state between product types', () => {
        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal__content h3').should(
            'contain',
            'Why are you unsubscribing from Product analytics + data stack?'
        )

        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Product analytics')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').eq(1).click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal__content h3').should('contain', 'Why are you unsubscribing from Session replay?')
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Session replay')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').should('have.value', 'Product analytics')
    })
})
