describe('Before Onboarding', () => {
    it.only('Navigate back to products when a product has not been set up', () => {
        cy.visit('/project/1/data-management/events')

        cy.get('[data-attr=top-bar-name] > span').contains('Products')
    })

    it.only('Navigate to a settings page even when a product has not been set up', () => {
        cy.visit('/settings/user')

        cy.get('[data-attr=top-bar-name] > span').contains('User')

        cy.visit('/settings/organization')

        cy.get('[data-attr=top-bar-name] > span').contains('Organization')
    })
})
