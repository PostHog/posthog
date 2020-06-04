describe('Onboarding', () => {
    it('Onboarding is visible', () => {
        cy.get('[data-attr=onboarding-button]').should('exist')
    })

    it('Onboarding popup', () => {
        cy.get('[data-attr=onboarding-button]').click()
        cy.get('[data-attr=onboarding-content]').should('exist')
        cy.get('[data-attr=onboarding-item-0]').should('exist')
    })

    it('Onboarding modal', () => {
        cy.get('[data-attr=onboarding-button]').click()
        cy.get('[data-attr=onboarding-item-0]').click()

        cy.get('[data-attr=onboarding-image]').should('exist')
        cy.get('[data-attr=onboarding-start-flow-button]').should('exist')
    })

    it('Onboarding start flow', () => {
        cy.get('[data-attr=onboarding-button]').click()
        cy.get('[data-attr=onboarding-item-0]').click()
        cy.get('[data-attr=onboarding-start-flow-button]').click()
        cy.get('[data-attr=tour-tooltip]').should('exist')
    })
})
