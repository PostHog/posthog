describe('Person', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click() // TODO: Adjust when releasing navigation-1775
        cy.contains('deborah.fernandez@gmail.com').click()
    })

    it('Can access person page', () => {
        cy.get('[data-row-key="email"] > :nth-child(1)').should('contain', 'email')
    })

    it('Events table loads', () => {
        cy.get('.events').should('exist')
    })

    // Add when feature flag for session recording is off
    // it('Sessions table loads', () => {})
})
