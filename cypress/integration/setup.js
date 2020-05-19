describe('Setup', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-setup]').click()
    })

    it('Setup loaded', () => {
        cy.get('h1').should('contain', 'Setup your PostHog account')
    })
})
